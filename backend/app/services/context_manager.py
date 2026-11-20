from typing import List, Dict, Optional
from app.core.config import settings
from app.core.logger import logger

def estimate_tokens(text: str) -> int:
    """Fast, reliable heuristic estimation: ~4 chars per token."""
    if not text:
        return 0
    return max(1, len(text) // 4)

def calculate_history_tokens(messages: List[Dict[str, str]]) -> int:
    """Calculates total estimated tokens across all messages."""
    return sum(estimate_tokens(m.get("content", "")) for m in messages)

class ConversationContextManager:
    """
    Manages conversational context window:
    - Retains the most recent N turns (configurable).
    - If total history exceeds token budget, condenses older turns into a rolling summary.
    """

    def __init__(
        self,
        max_turns: Optional[int] = None,
        token_budget: Optional[int] = None
    ):
        self.max_turns = max_turns or settings.CONTEXT_WINDOW_TURNS
        self.token_budget = token_budget or settings.CONTEXT_TOKEN_BUDGET

    def create_fallback_summary(self, older_turns: List[Dict[str, str]]) -> str:
        """Creates an extractive running summary of older turns."""
        summary_points = []
        for msg in older_turns:
            role = msg.get("role", "unknown")
            content = msg.get("content", "").strip()
            if not content:
                continue
            first_sentence = content.split(".")[0].strip()
            if len(first_sentence) > 80:
                first_sentence = first_sentence[:77] + "..."
            summary_points.append(f"{role.capitalize()}: {first_sentence}")

        return "; ".join(summary_points)

    async def prepare_context(
        self,
        messages: List[Dict[str, str]],
        llm_provider = None,
        model: str = ""
    ) -> List[Dict[str, str]]:
        """
        Trims and condenses dialogue history to fit within turn count and token budget.
        """
        if not messages:
            return []

        # If already within bounds, return as is
        total_tokens = calculate_history_tokens(messages)
        if len(messages) <= self.max_turns and total_tokens <= self.token_budget:
            return messages

        # Separate into older turns to summarize and recent turns to keep in full fidelity
        split_idx = max(1, len(messages) - self.max_turns)
        older_turns = messages[:split_idx]
        recent_turns = messages[split_idx:]

        # Ensure recent turns alone don't exceed budget
        while len(recent_turns) > 2 and calculate_history_tokens(recent_turns) > self.token_budget:
            older_turns.append(recent_turns.pop(0))

        # Generate summary of older turns
        summary_text = ""
        if llm_provider and older_turns:
            try:
                summary_prompt = (
                    "Summarize the key facts, decisions, and topics from this earlier part of the conversation "
                    "in 2-3 concise sentences:"
                )
                dialogue_text = "\n".join(f"{m['role']}: {m['content']}" for m in older_turns)
                summary_text = await llm_provider.generate(
                    messages=[{"role": "user", "content": f"{dialogue_text}\n\n{summary_prompt}"}],
                    system_prompt="You are an expert conversation summarizer.",
                    temperature=0.2,
                    model=model
                )
            except Exception as e:
                logger.warning(f"LLM summarization failed, falling back to extractive summary: {e}")
                summary_text = self.create_fallback_summary(older_turns)
        else:
            summary_text = self.create_fallback_summary(older_turns)

        # Inject condensed summary as a system turn preceding recent turns
        condensed_context = []
        if summary_text:
            condensed_context.append({
                "role": "system",
                "content": f"[Earlier conversation summary: {summary_text.strip()}]"
            })

        condensed_context.extend(recent_turns)
        return condensed_context
