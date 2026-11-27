"""Synthetic credential gate: never passes secret material through IPC.

Only imported by offline/hosted CI tests. This is not a live credential
delivery mechanism; the synthetic WordPress DB already holds the canary.
"""
import hmac

from .research_credentials import SecretBinding,load_pinned
from .research_receipts import plan_checked


class FixtureCredentialGate:
    def __init__(self,client,binding):
        if not isinstance(binding,SecretBinding) or binding.store!="7":
            raise ValueError("Synthetic store only")
        self.client=client
        self.binding=binding

    def __call__(self,plan,receipt):
        plan_checked(plan)
        if plan["store"]!="7" or receipt["plan"]!=plan or receipt["state"]!="reserved":
            raise ValueError("Matching durable fixture reservation required")
        secret=load_pinned(self.client,self.binding)
        if not hmac.compare_digest(secret.token,"ci-only-token-canary"):
            raise ValueError("Synthetic credential required; no IPC emitted")
