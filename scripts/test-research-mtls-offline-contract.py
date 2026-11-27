"""Synthetic specification only: no delivery, identity boundary or security proof."""
import unittest


# Names describe intended content, not files, credentials, or permissions.
PACKAGES = {
    "proxy": frozenset(("ca_public", "server_cert", "server_key", "client_der_pin")),
    "worker": frozenset(("ca_public", "client_cert", "client_key", "server_name")),
}
REQUIRED_EVIDENCE = frozenset((
    "reviewed_threat_model",
    "real_identity_cross_access_denial",
    "ephemeral_issuance_and_isolated_transport",
    "cryptographic_validation",
    "failure_and_cleanup",
    "platform_limitations",
))


def specification_accepts_package(role, fields):
    """Check only the proposed shape, not access control or field values."""
    return role in PACKAGES and frozenset(fields) == PACKAGES[role]


def specification_ready(evidence):
    """Illustrate missing-evidence rejection; this is not an approval process."""
    return REQUIRED_EVIDENCE <= frozenset(evidence)


class OfflineDeliveryContract(unittest.TestCase):
    def test_exact_recipient_shapes(self):
        for role, fields in PACKAGES.items():
            with self.subTest(role=role):
                self.assertTrue(specification_accepts_package(role, fields))
                for field in fields:
                    self.assertFalse(specification_accepts_package(role, fields - {field}))
                self.assertFalse(specification_accepts_package(role, fields | {"ca_private_key"}))
        self.assertFalse(specification_accepts_package("controller", PACKAGES["proxy"]))

    def test_cross_delivery_and_private_keys_rejected(self):
        self.assertFalse(specification_accepts_package("proxy", PACKAGES["worker"]))
        self.assertFalse(specification_accepts_package("worker", PACKAGES["proxy"]))
        self.assertFalse(specification_accepts_package("proxy", PACKAGES["proxy"] | {"client_key"}))
        self.assertFalse(specification_accepts_package("worker", PACKAGES["worker"] | {"server_key"}))

    def test_every_evidence_category_is_required(self):
        self.assertFalse(specification_ready(()))
        for item in REQUIRED_EVIDENCE:
            with self.subTest(missing=item):
                self.assertFalse(specification_ready(REQUIRED_EVIDENCE - {item}))
        # Synthetic labels do not constitute actual evidence or authorize a run.
        self.assertTrue(specification_ready(REQUIRED_EVIDENCE))


if __name__ == "__main__":
    unittest.main()
