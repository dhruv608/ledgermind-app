import json
from typing import Dict, Any, List, Optional, Tuple
from botocore.exceptions import ClientError
from backend.app.core.config import settings

MIN_REPLY_TOKENS = 8000


class BedrockAIService:
    def __init__(self):
        # With the keys in .env when given; on the server (no keys) the server's own AWS role
        from backend.app.core.s3 import aws_client
        self.client = aws_client("bedrock-runtime", settings.BEDROCK_REGION or settings.AWS_REGION)

    def invoke_model(self, prompt: str, model_id: Optional[str] = None, max_tokens: int = 500, temperature: float = 0.1) -> str:
        return self.invoke_model_reporting(prompt, model_id, max_tokens, temperature)[0]

    def invoke_model_reporting(self, prompt: str, model_id: Optional[str] = None, max_tokens: int = 500,
                               temperature: float = 0.1) -> Tuple[str, str]:
        """The model's reply and the model that gave it (the backup model answers if the main one fails)."""
        if not self.client:
            raise RuntimeError("AWS Bedrock client is not configured.")

        selected_model = model_id or settings.BEDROCK_PRIMARY_MODEL
        # Models that reason before answering use part of the limit for that: never cut the answer off
        max_tokens = max(max_tokens, MIN_REPLY_TOKENS)

        try:
            # Build inference config based on model type
            inf_config = {"maxTokens": max_tokens}
            if "kimi" not in selected_model.lower():
                inf_config["temperature"] = temperature

            response = self.client.converse(
                modelId=selected_model,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig=inf_config
            )

            from backend.app.core import ai_usage
            ai_usage.record(selected_model, "text", prompt, response)
            contents = response["output"]["message"]["content"]
            # Extract plain text from response blocks (reasoning models return extra blocks)
            text_block = next((c["text"] for c in contents if "text" in c), "")
            return text_block.strip(), selected_model

        except ClientError as e:
            # Fallback to secondary model if primary fails
            if selected_model != settings.BEDROCK_REASONING_MODEL:
                return self.invoke_model_reporting(prompt, model_id=settings.BEDROCK_REASONING_MODEL, max_tokens=max_tokens)
            raise RuntimeError(f"Bedrock invocation failed: {e}")

    def map_accounts_batch(self, accounts: List[Dict[str, Any]], chart_text: str) -> List[Dict[str, Any]]:
        """Map a batch of client accounts to the firm chart. Returns one {i, code, confidence, reason} per account it answered."""
        lines = []
        for i, a in enumerate(accounts):
            bal = float(a.get("net") or 0.0)
            side = "debit" if bal > 0 else "credit" if bal < 0 else "nil"
            parts = [f'{i}. "{a["name"]}"', f"balance {bal:,.2f} ({side})"]
            if a.get("account_type"):
                parts.append(f'type in client software: {a["account_type"]}')
            if a.get("samples"):
                parts.append("sample transactions: " + "; ".join(a["samples"]))
            if a.get("examples"):
                parts.append("the accountant coded similar accounts: " + "; ".join(a["examples"]))
            lines.append(" | ".join(parts))

        prompt = f"""You are a UK chartered accountant mapping a client's trial balance to the firm's standard chart of accounts.

Client accounts (positive balance = debit, negative = credit):
{chr(10).join(lines)}

Any number at the start of a client account name is the CLIENT'S OWN code. It is NOT a code in the firm chart. Ignore it.

For each client account pick exactly ONE code from the firm chart below (format: code | name | section | class).
If you are unsure, still pick the closest code but give a low confidence.
{SECTION_RULE}
Where "the accountant coded similar accounts" is given, those are this firm's own past choices: follow them when the
account is the same kind of thing (the firm's habit decides between close codes), and ignore them when it is not.
{chart_text}

Reply with a JSON array only, one object per client account:
[{{"i": 0, "code": "0000", "confidence": 0.0-1.0, "reason": "one short sentence"}}]"""

        raw, model = self.invoke_model_reporting(prompt, max_tokens=150 * len(accounts) + 200, temperature=0)
        start, end = raw.find("["), raw.rfind("]")
        if start == -1 or end == -1:
            raise ValueError(f"No JSON array in model reply: {raw[:200]}")
        answers = json.loads(raw[start:end + 1])
        for a in answers:
            if isinstance(a, dict):
                a["model"] = model
        return answers

bedrock_ai = BedrockAIService()

# The firm chart has the same kind of cost in more than one section (advertising 3280 in overheads and marketing 1670
# in cost of sales; telephone 3290 and 1690). The accountant's rule: an overhead unless it is plainly a direct cost
SECTION_RULE = """The chart often has the same kind of cost both in "Cost of sales" / "Distribution costs" and in the
overhead sections ("General admin", "Employee costs", "Premises expenses" ...): for example advertising 3280 (overheads)
and marketing 1670 (cost of sales), telephone 3290 and 1690. Use the OVERHEAD code by default. Use a cost of sales or
distribution code only when the account is plainly a direct cost of what the client sells: purchases or materials for
resale or production, subcontractors and direct labour on jobs, carriage on goods sold, or the name says "direct" /
"cost of sales"."""


def map_account_options(account: Dict[str, Any], chart_text: str) -> List[Dict[str, Any]]:
    """The AI's best 3 firm codes for one client account, most likely first: [{code, confidence, reason}]."""
    bal = float(account.get("net") or 0.0)
    side = "debit" if bal > 0 else "credit" if bal < 0 else "nil"
    parts = [f'"{account["name"]}"', f"balance {bal:,.2f} ({side})"]
    if account.get("account_type"):
        parts.append(f'type in client software: {account["account_type"]}')
    if account.get("samples"):
        parts.append("sample transactions: " + "; ".join(account["samples"]))
    prompt = f"""You are a UK chartered accountant mapping one client trial balance account to the firm's standard chart of accounts.

Client account: {" | ".join(parts)}

Any number at the start of the client account name is the CLIENT'S OWN code, not a firm code. Ignore it.

Give the 3 most likely codes from the firm chart below (format: code | name | section | class), best first. They must be
3 different codes. Confidences are your probability that each is right.
{SECTION_RULE}
{chart_text}

Reply with a JSON array only:
[{{"code": "0000", "confidence": 0.0-1.0, "reason": "one short sentence"}}]"""
    raw, _ = bedrock_ai.invoke_model_reporting(prompt, max_tokens=400, temperature=0)
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array in model reply: {raw[:200]}")
    return [a for a in json.loads(raw[start:end + 1]) if isinstance(a, dict)][:3]
