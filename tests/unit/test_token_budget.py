from app.context.token_budget import estimate_token_count


def test_estimate_token_count_counts_ascii_chunks_and_cjk_chars() -> None:
    assert estimate_token_count("") == 0
    assert estimate_token_count("abcd") == 1
    assert estimate_token_count("abcdefgh") == 2
    assert estimate_token_count("查看 git 状态") >= 4


def test_estimate_token_count_accepts_nested_json_like_values() -> None:
    payload = {
        "summary": "Read README.md",
        "matches": ["alpha beta", "查看状态"],
    }

    assert estimate_token_count(payload) >= estimate_token_count("Read README.md")
