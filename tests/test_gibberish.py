from app.main import _gibberish


def test_gibberish_rejects_mashed_keys():
    assert _gibberish("fgfur")
    assert _gibberish("asdfg")
    assert _gibberish("aaaaaa")
    assert _gibberish("!!!")
    assert _gibberish("hi")
    assert _gibberish("xyz")


def test_gibberish_allows_real_prompts():
    assert not _gibberish("write a story about a dog saving his owner")
    assert not _gibberish("golf")
    assert not _gibberish("rhythm")
    assert not _gibberish("clock")
    assert not _gibberish("street")
    assert not _gibberish("gym story")
