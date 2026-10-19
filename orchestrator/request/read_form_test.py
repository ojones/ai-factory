import unittest

from request import read_form

FORM = "### App name\n\n{app}\n\n### What should change?\n\n{task}\n\n### Cost cap override (USD)\n\n{cap}\n"
NEW_APP = "### What should be built?\r\n\r\nA notes app\r\nwith tags\r\n\r\n### Cost cap override (USD)\r\n\r\n{cap}\r\n"


class Sections(unittest.TestCase):
    def test_a_section_is_the_text_under_its_heading_with_blanks_trimmed_and_crlf_ignored(self):
        self.assertEqual(read_form.form_section(NEW_APP.format(cap="3"), "What should be built?"), "A notes app\nwith tags")
        self.assertEqual(read_form.form_section("### A\n\nx\n\n### B\n\ny\n", "B"), "y")

    def test_a_missing_section_or_body_is_empty(self):
        self.assertEqual(read_form.form_section("### A\n\nx\n", "B"), "")
        self.assertEqual(read_form.form_section(None, "A"), "")


class AppName(unittest.TestCase):
    def test_the_app_name_is_read_and_checked(self):
        self.assertEqual(read_form.app_name(FORM.format(app="recipe-box", task="x", cap="")), "recipe-box")
        for bad in ("", "_No response_", "Recipe Box", "-x", "a" * 31, "my_app", "x/../y"):
            with self.assertRaises(ValueError, msg=bad):
                read_form.app_name(FORM.format(app=bad, task="x", cap=""))


class ReadRequest(unittest.TestCase):
    def test_a_new_app_and_an_update_both_give_their_request(self):
        self.assertEqual(read_form.read_request(NEW_APP.format(cap="_No response_"), 2.0, 10.0), ("A notes app\nwith tags", 2.0))
        self.assertEqual(read_form.read_request(FORM.format(app="a", task="Add search\nby title", cap="$3"), 2.0, 10.0), ("Add search\nby title", 3.0))

    def test_the_cost_cap_override_must_be_a_number_above_zero_and_within_the_ceiling(self):
        self.assertEqual(read_form.read_request(NEW_APP.format(cap="$3.5"), 2.0, 10.0)[1], 3.5)
        self.assertEqual(read_form.read_request(NEW_APP.format(cap="10"), 2.0, 10.0)[1], 10.0)
        for bad in ("10.01", "0", "-1", "abc"):
            with self.assertRaises(ValueError, msg=bad):
                read_form.read_request(NEW_APP.format(cap=bad), 2.0, 10.0)

    def test_an_empty_request_is_refused(self):
        for body in ("### What should be built?\n\n_No response_\n", FORM.format(app="a", task="_No response_", cap=""), "", None):
            with self.assertRaises(ValueError):
                read_form.read_request(body, 2.0, 10.0)


if __name__ == "__main__":
    unittest.main()
