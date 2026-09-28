"""Unit tests for links.parse_link / find_links. Run: python -m unittest discover -s tests"""

import unittest

from links import LinkError, find_links, parse_link


class FindLinksTests(unittest.TestCase):
    def test_multiple_links(self):
        text = "check https://t.me/foo/123 and t.me/bar/456 thanks"
        self.assertEqual(find_links(text), ["https://t.me/foo/123", "t.me/bar/456"])

    def test_no_links(self):
        self.assertEqual(find_links("hello world"), [])

    def test_telegram_me_and_dog(self):
        self.assertEqual(len(find_links("t.me/a/1 telegram.dog/b/2")), 2)

    def test_trailing_punctuation_stripped(self):
        self.assertEqual(find_links("see t.me/foo/123."), ["t.me/foo/123"])


class ParsePublicTests(unittest.TestCase):
    def test_public_post(self):
        self.assertEqual(parse_link("t.me/durov/123"), ("message", "durov", 123))

    def test_public_with_scheme_and_www(self):
        self.assertEqual(
            parse_link("https://www.telegram.me/durov/99"),
            ("message", "durov", 99),
        )

    def test_public_topic_link_last_id_wins(self):
        self.assertEqual(parse_link("t.me/mygroup/45/678"), ("message", "mygroup", 678))

    def test_query_string_ignored(self):
        self.assertEqual(
            parse_link("https://t.me/durov/123?single"),
            ("message", "durov", 123),
        )

    def test_bare_username_is_join(self):
        self.assertEqual(parse_link("t.me/pyrogramchat"), ("join", "pyrogramchat"))


class ParsePrivateTests(unittest.TestCase):
    def test_private_post(self):
        self.assertEqual(parse_link("t.me/c/2222333/123"), ("message", -1002222333, 123))

    def test_private_topic(self):
        self.assertEqual(
            parse_link("https://t.me/c/2222333/45/678"),
            ("message", -1002222333, 678),
        )

    def test_private_missing_msg(self):
        with self.assertRaises(LinkError):
            parse_link("t.me/c/2222333")


class ParseInviteTests(unittest.TestCase):
    def test_joinchat(self):
        kind, url = parse_link("t.me/joinchat/AbCdEf123")
        self.assertEqual(kind, "invite")
        self.assertEqual(url, "https://t.me/joinchat/AbCdEf123")

    def test_plus_invite(self):
        kind, url = parse_link("https://t.me/+AbCdEf123")
        self.assertEqual(kind, "invite")
        self.assertEqual(url, "https://t.me/joinchat/AbCdEf123")


class ParseErrorTests(unittest.TestCase):
    def test_non_telegram_host(self):
        with self.assertRaises(LinkError):
            parse_link("https://example.com/foo/1")

    def test_empty(self):
        with self.assertRaises(LinkError):
            parse_link("")

    def test_non_numeric_msg_id(self):
        with self.assertRaises(LinkError):
            parse_link("t.me/foo/abc")


if __name__ == "__main__":
    unittest.main()
