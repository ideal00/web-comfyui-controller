import unittest

from easy_panel import workflow_primary_seed


class SeedQuickActionsTests(unittest.TestCase):
    def test_primary_sampler_seed_is_returned_as_exact_text(self):
        seed = 734729834729834729
        workflow = {
            "loader": {"class_type": "CheckpointLoaderSimple", "inputs": {}},
            "sample": {"class_type": "KSampler", "inputs": {"seed": seed}},
        }
        self.assertEqual(workflow_primary_seed(workflow), str(seed))

    def test_missing_sampler_has_no_seed(self):
        self.assertEqual(workflow_primary_seed({"a": {"class_type": "SaveImage", "inputs": {}}}), "")


if __name__ == "__main__":
    unittest.main()
