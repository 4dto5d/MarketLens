from dataclasses import dataclass

import pytest

from local_presence_miner.config import SenderInfo


@dataclass(frozen=True)
class OutboundFixture:
    sender: SenderInfo = SenderInfo(
        name="Test Operator", business_name="Fixture Studio", reply_email="operator@example.com",
        phone="555-010-0100", postal_address="123 Fixture Street, Test City",
        opt_out_line="Reply opt out to stop contact.",
    )

    def body(self, message: str) -> str:
        return "\n".join((message, self.sender.name, self.sender.business_name, self.sender.reply_email,
                          self.sender.phone, self.sender.postal_address, self.sender.opt_out_line))


@pytest.fixture
def outbound():
    """Synthetic, explicitly configured sender; does not bypass approval validation."""
    return OutboundFixture()
