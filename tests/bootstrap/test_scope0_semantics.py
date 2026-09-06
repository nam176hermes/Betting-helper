from moj_discovery.governance import validate_semantic_vector_file


def test_scope_counterexamples_are_present() -> None:
    validate_semantic_vector_file("scope-semantic-v1.json")
