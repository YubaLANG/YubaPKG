import unittest

from pkg.semver import Version, satisfies, validate_requirement


class SemanticVersionTests(unittest.TestCase):
    def test_orders_releases_and_prereleases_by_semver_rules(self):
        ordered = [
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-alpha.beta",
            "1.0.0-beta",
            "1.0.0-beta.2",
            "1.0.0-beta.11",
            "1.0.0-rc.1",
            "1.0.0",
        ]
        self.assertEqual(
            [str(version) for version in sorted(map(Version.parse, reversed(ordered)))],
            ordered,
        )
        self.assertEqual(Version.parse("1.2.3+one"), Version.parse("1.2.3+two"))

    def test_matches_exact_caret_tilde_comparison_and_wildcard_requirements(self):
        cases = (
            ("1.4.0", "^1.2.3", True),
            ("2.0.0", "^1.2.3", False),
            ("0.2.9", "^0.2.3", True),
            ("0.3.0", "^0.2.3", False),
            ("1.2.9", "~1.2.3", True),
            ("1.3.0", "~1.2.3", False),
            ("1.7.0", ">=1.2.0, <2.0.0", True),
            ("1.7.0", "1.x", True),
            ("2.0.0", "1.x", False),
            ("1.2.0", "1.2.*", True),
            ("1.3.0", "1.2.*", False),
            ("1.2.3-beta", ">=1.2.3-beta <1.2.3", True),
            ("1.2.3-beta", "^1.2.0", False),
            ("1.2.4-beta", ">=1.2.3-beta <2.0.0", False),
        )
        for version, requirement, expected in cases:
            with self.subTest(version=version, requirement=requirement):
                self.assertEqual(satisfies(version, requirement), expected)

    def test_rejects_malformed_versions_and_requirements(self):
        for value in ("1.2", "01.2.3", "1.2.3-01"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Version.parse(value)
        for requirement in ("", ">=1.2", "^1.2.3 || ^2.0.0", "1.x.2"):
            with self.subTest(requirement=requirement), self.assertRaises(ValueError):
                validate_requirement(requirement)


if __name__ == "__main__":
    unittest.main()
