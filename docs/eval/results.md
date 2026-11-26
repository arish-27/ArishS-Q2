# RAG Evaluation Results (Real Run)

| Metric | Value |
| --- | --- |
| In-Knowledge Questions | 20 |
| Retrieval Hit Rate (top-4) | 100.0% |
| Keyword Match Accuracy | 100.0% |
| LLM-as-Judge Avg Score | 1.000 / 1.0 |
| Out-of-Knowledge Abstention (5 Qs) | 100.0% |
| Retrieval Latency (avg / p95) | 1199.5 ms / 875.9 ms |
| LLM TTFT (avg / p95) | 1238.0 ms / 2147.9 ms |
| Total Latency (avg / p95) | 2451.2 ms / 4395.7 ms |

## Per-Question Breakdown

| # | Hit | KW | Judge | Ret (ms) | TTFT (ms) | Total (ms) | Question |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Yes | Yes | 1.00 | 875.9 | 1266.7 | 2162.7 | When was AetherGrid Robotics founded and by whom? |
| 2 | Yes | Yes | 1.00 | 594.3 | 3786.3 | 4395.7 | Where is AetherGrid Robotics headquarters located? |
| 3 | Yes | Yes | 1.00 | 12445.4 | 1110.5 | 13568.9 | Which European city has an AetherGrid logistics depot? |
| 4 | Yes | Yes | 1.00 | 671.0 | 882.0 | 1560.4 | What is the payload capacity and battery runtime of Rover-S1? |
| 5 | Yes | Yes | 1.00 | 595.2 | 957.0 | 1563.8 | How much does Rover-S1 cost on the RaaS monthly plan? |
| 6 | Yes | Yes | 1.00 | 621.3 | 1331.7 | 1966.5 | What is the payload capacity of Titan-M4? |
| 7 | Yes | Yes | 1.00 | 601.3 | 933.2 | 1546.8 | How much is the FleetOS Enterprise License per warehouse site? |
| 8 | Yes | Yes | 1.00 | 660.6 | 1889.7 | 2559.7 | How much do additional robot seats cost in FleetOS beyond 50 robots? |
| 9 | Yes | Yes | 1.00 | 591.9 | 948.5 | 1544.9 | How long is the standard hardware warranty on new robots? |
| 10 | Yes | Yes | 1.00 | 663.8 | 879.5 | 1557.0 | What is the warranty on robot batteries? |
| 11 | Yes | Yes | 1.00 | 607.8 | 1219.5 | 1863.2 | What uptime does the Enterprise SLA guarantee? |
| 12 | Yes | Yes | 1.00 | 507.4 | 1019.2 | 1537.5 | What is the service credit if unscheduled downtime exceeds the SLA? |
| 13 | Yes | Yes | 1.00 | 514.3 | 1030.8 | 1555.5 | Within how many days can unopened hardware purchases be returned? |
| 14 | Yes | Yes | 1.00 | 670.6 | 1142.6 | 1822.7 | How many business days does it take to process approved refunds? |
| 15 | Yes | Yes | 1.00 | 546.8 | 2147.9 | 2702.0 | What is the emergency hotline for P1 fleet-halt incidents? |
| 16 | Yes | Yes | 1.00 | 526.5 | 735.3 | 1305.8 | What are the live support hours in IST? |
| 17 | Yes | Yes | 1.00 | 520.1 | 1021.4 | 1549.8 | Which security certifications did AetherGrid achieve in 2025? |
| 18 | Yes | Yes | 1.00 | 538.4 | 872.2 | 1416.6 | What encryption does FleetOS use at rest? |
| 19 | Yes | Yes | 1.00 | 619.6 | 804.0 | 1435.5 | How long does it take for certified partners to receive sandbox credentials? |
| 20 | Yes | Yes | 1.00 | 617.2 | 782.9 | 1409.6 | What is the production REST API rate limit per tenant key? |
