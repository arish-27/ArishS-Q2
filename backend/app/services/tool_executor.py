import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.core.logger import logger


class ToolValidationError(Exception):
    """Raised when tool arguments fail JSON schema validation."""
    pass


class SSRFBlockedError(Exception):
    """Raised when a webhook URL targets a disallowed scheme or private/internal IP."""
    pass


BUILTIN_TOOL_PRESETS: Dict[str, Dict[str, Any]] = {
    "get_current_time": {
        "name": "get_current_time",
        "description": "Returns the current UTC date and time (or requested timezone label).",
        "parameters_schema": json.dumps({
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "Optional timezone name, e.g. UTC or IST"}
            },
            "required": [],
        }),
        "is_sensitive": False,
        "execution_type": "built_in",
    },
    "get_weather": {
        "name": "get_weather",
        "description": "Returns current mock weather conditions for a city.",
        "parameters_schema": json.dumps({
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name, e.g. Bengaluru or San Francisco"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["location"],
        }),
        "is_sensitive": False,
        "execution_type": "built_in",
    },
    "book_appointment": {
        "name": "book_appointment",
        "description": "Books an appointment slot on the calendar (requires user confirmation).",
        "parameters_schema": json.dumps({
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Meeting or appointment title"},
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "time": {"type": "string", "description": "Time in HH:MM format"},
                "attendee_email": {"type": "string", "description": "Optional attendee email"},
            },
            "required": ["title", "date", "time"],
        }),
        "is_sensitive": True,
        "execution_type": "built_in",
    },
    "send_email": {
        "name": "send_email",
        "description": "Sends an email to a recipient (requires user confirmation).",
        "parameters_schema": json.dumps({
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body content"},
            },
            "required": ["to", "subject", "body"],
        }),
        "is_sensitive": True,
        "execution_type": "built_in",
    },
}

_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def _is_disallowed_ip(ip_str: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def validate_webhook_url_ssrf(url: str) -> str:
    """
    Validates that a webhook URL uses http(s) and does not resolve to
    loopback, private, link-local, metadata, or reserved IP ranges.
    """
    if not url or not url.strip():
        raise SSRFBlockedError("Webhook URL is required.")
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFBlockedError(f"Blocked URL scheme '{parsed.scheme}': only http and https are allowed.")
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise SSRFBlockedError("Webhook URL must include a valid hostname.")
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".local") or hostname.endswith(".internal"):
        raise SSRFBlockedError(f"Blocked internal/loopback hostname '{hostname}'.")

    # Direct IP literal check
    try:
        ipaddress.ip_address(hostname)
        if _is_disallowed_ip(hostname):
            raise SSRFBlockedError(f"Blocked private/loopback/link-local IP '{hostname}'.")
        return url.strip()
    except ValueError:
        pass

    # DNS resolution check
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"DNS resolution failed for '{hostname}': {exc}") from exc

    if not infos:
        raise SSRFBlockedError(f"No DNS records found for '{hostname}'.")

    for info in infos:
        resolved_ip = info[4][0]
        if _is_disallowed_ip(resolved_ip):
            raise SSRFBlockedError(
                f"Blocked DNS resolution '{hostname}' -> '{resolved_ip}' (private/internal/link-local)."
            )

    return url.strip()


def validate_tool_arguments(schema_str: str, arguments: Any) -> Dict[str, Any]:
    """Validates tool call arguments against the tool's JSON Schema."""
    if not isinstance(arguments, dict):
        raise ToolValidationError("Tool arguments must be a JSON object.")

    try:
        schema = json.loads(schema_str) if isinstance(schema_str, str) else (schema_str or {})
    except json.JSONDecodeError as exc:
        raise ToolValidationError(f"Invalid tool JSON schema: {exc}") from exc

    required = schema.get("required", [])
    if isinstance(required, list):
        missing = [k for k in required if k not in arguments or arguments[k] is None]
        if missing:
            raise ToolValidationError(f"Missing required argument(s): {', '.join(missing)}")

    props = schema.get("properties", {})
    if isinstance(props, dict):
        for key, val in arguments.items():
            if key not in props:
                continue
            prop_spec = props[key]
            expected_type = prop_spec.get("type")
            if expected_type == "string" and not isinstance(val, str):
                raise ToolValidationError(f"Argument '{key}' must be a string.")
            elif expected_type == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
                raise ToolValidationError(f"Argument '{key}' must be an integer.")
            elif expected_type == "number" and (not isinstance(val, (int, float)) or isinstance(val, bool)):
                raise ToolValidationError(f"Argument '{key}' must be a number.")
            elif expected_type == "boolean" and not isinstance(val, bool):
                raise ToolValidationError(f"Argument '{key}' must be a boolean.")
            elif expected_type == "array" and not isinstance(val, list):
                raise ToolValidationError(f"Argument '{key}' must be an array.")
            elif expected_type == "object" and not isinstance(val, dict):
                raise ToolValidationError(f"Argument '{key}' must be an object.")

            enum_vals = prop_spec.get("enum")
            if isinstance(enum_vals, list) and val not in enum_vals:
                raise ToolValidationError(f"Argument '{key}' must be one of {enum_vals}.")

    return arguments


def _execute_builtin(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if name == "get_current_time":
        tz_label = args.get("timezone") or "UTC"
        now_utc = datetime.now(timezone.utc)
        return {
            "timezone": tz_label,
            "iso": now_utc.isoformat(),
            "formatted": now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
    if name == "get_weather":
        loc = args.get("location", "Unknown")
        unit = args.get("unit", "celsius")
        temp = 26 if unit == "celsius" else 79
        return {
            "location": loc,
            "temperature": temp,
            "unit": unit,
            "condition": "Partly cloudy",
            "humidity_pct": 58,
            "mock": True,
        }
    if name == "book_appointment":
        return {
            "status": "booked",
            "confirmation_id": f"APT-{int(time.time()) % 100000}",
            "title": args.get("title"),
            "date": args.get("date"),
            "time": args.get("time"),
            "attendee_email": args.get("attendee_email"),
            "mock": True,
        }
    if name == "send_email":
        return {
            "status": "sent",
            "message_id": f"MSG-{int(time.time()) % 100000}",
            "to": args.get("to"),
            "subject": args.get("subject"),
            "mock": True,
        }
    return {"status": "ok", "tool": name, "arguments": args, "mock": True}


def _render_body_template(template_str: Optional[str], args: Dict[str, Any]) -> Any:
    if not template_str or not template_str.strip():
        return args
    rendered = template_str
    for k, v in args.items():
        rendered = rendered.replace(f"{{{{{k}}}}}", str(v))
    try:
        return json.loads(rendered)
    except json.JSONDecodeError:
        return rendered


async def execute_tool(tool: Any, raw_arguments: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
    """
    Validates arguments against `tool.parameters_schema` and executes built-in, mock,
    or SSRF-protected HTTP webhook tools. Returns `(result_dict, duration_ms)`.
    """
    start = time.perf_counter()
    args = validate_tool_arguments(tool.parameters_schema, raw_arguments)
    exec_type = (tool.execution_type or "mock").lower()

    if exec_type == "built_in":
        result = _execute_builtin(tool.name, args)
        return result, round((time.perf_counter() - start) * 1000.0, 2)

    if exec_type == "mock":
        result = {
            "status": "ok",
            "tool": tool.name,
            "arguments": args,
            "mock": True,
        }
        return result, round((time.perf_counter() - start) * 1000.0, 2)

    if exec_type == "webhook":
        safe_url = validate_webhook_url_ssrf(tool.webhook_url or "")
        method = (getattr(tool, "webhook_method", None) or "POST").upper()
        headers = {}
        try:
            headers = json.loads(getattr(tool, "webhook_headers", "{}") or "{}")
        except json.JSONDecodeError:
            headers = {}

        body_payload = _render_body_template(getattr(tool, "webhook_body_template", None), args)
        max_bytes = 65536
        timeout = httpx.Timeout(5.0)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            if method == "GET":
                resp = await client.get(safe_url, params=args, headers=headers)
            elif isinstance(body_payload, (dict, list)):
                resp = await client.request(method, safe_url, json=body_payload, headers=headers)
            else:
                resp = await client.request(method, safe_url, content=str(body_payload), headers=headers)

        raw_bytes = resp.content[:max_bytes]
        text_body = raw_bytes.decode("utf-8", errors="replace")
        try:
            parsed_body = json.loads(text_body)
        except json.JSONDecodeError:
            parsed_body = text_body

        return {
            "status_code": resp.status_code,
            "truncated": len(resp.content) > max_bytes,
            "body": parsed_body,
        }, round((time.perf_counter() - start) * 1000.0, 2)

    raise ToolValidationError(f"Unknown tool execution_type '{exec_type}'.")
