import unittest

from engine.scanner import compute_risk
from engine.scoring import (
    label_pool_risk,
    public_risk_label,
    score_pool,
    score_pool_volatility,
    score_signal,
    score_signal_movement,
    score_tvl_stability,
    strength_label,
)
from signal_intelligence import build_reason, risk_tags, signal_strength_score


class ScoringCharacterizationTests(unittest.TestCase):
    def test_provider_risk_scoring_preserves_current_penalties(self):
        result = compute_risk(
            {
                "tvlUsd": 5_000_000,
                "apy": 35,
                "stablecoin": False,
                "ilRisk": "yes",
                "chain": "Sonic",
                "category": "Leveraged LP",
                "project": "beefy",
            }
        )

        self.assertEqual(result["risk_score"], 10)
        self.assertEqual(result["risk_label"], "High")
        self.assertEqual(
            result["risk_reasons"],
            "less battle-tested chain: Sonic; modest TVL; high APY; volatile asset exposure",
        )

    def test_public_signal_scoring_preserves_current_formula(self):
        signal = {
            "apy": 40,
            "tvl": 100_000_000,
            "trend_score": 20,
            "stablecoin": True,
            "chain": "Base",
            "category": "Lending",
            "risk_score": 4,
        }

        score = score_signal(signal)

        self.assertEqual(score, 78)
        self.assertEqual(strength_label(score), "Strong")
        self.assertEqual(public_risk_label(signal, score), "Low")

    def test_signal_movement_score_handles_zero_and_default_inputs(self):
        self.assertEqual(score_signal_movement(0, 0, 0), 0.0)
        self.assertEqual(score_signal_movement(None, None, None), 0.0)

    def test_signal_movement_score_uses_absolute_negative_deltas(self):
        self.assertEqual(score_signal_movement(-10, -20, 5), 12.5)

    def test_enrichment_strength_and_reason_preserve_current_formula(self):
        signal = {
            "signal": "Whale inflow",
            "apy": 40,
            "tvl": 100_000_000,
            "trend_score": 20,
            "stablecoin": True,
            "category": "LP",
            "risk_score": 4,
            "risk_label": "Moderate",
            "strength_label": "High conviction",
        }

        self.assertEqual(signal_strength_score(signal), 81)
        self.assertEqual(
            risk_tags(signal),
            ["deep liquidity", "very high APY", "stable exposure", "LP strategy"],
        )
        self.assertEqual(
            build_reason(signal),
            "Whale inflow • high conviction setup • 40.00% APY • large TVL base • moderate risk profile",
        )

    def test_ui_pool_risk_scoring_preserves_current_formula(self):
        row = {
            "apy": 30,
            "apyReward": 12,
            "stablecoin": False,
            "exposure": "multi",
            "poolMeta": "Vault",
            "tvl_stability_score": 54,
            "audit_score": 60,
            "protocol_age_score": 58,
        }

        row["pool_volatility_score"] = score_pool_volatility(row)

        self.assertEqual(score_tvl_stability(10_000_000), 54)
        self.assertEqual(row["pool_volatility_score"], 68)
        self.assertEqual(score_pool(row), 100)
        self.assertEqual(label_pool_risk(100), "Speculative")
        self.assertEqual(score_signal_movement(-10, 20, 5), 12.5)


if __name__ == "__main__":
    unittest.main()
