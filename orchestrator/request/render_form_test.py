import unittest

from request import read_form, render_form


class FormBody(unittest.TestCase):
    def test_a_rendered_body_reads_back_as_the_same_app_request_and_the_default_cap(self):
        body = render_form.form_body("demo", "Add tags\nto notes")
        self.assertEqual(read_form.app_name(body), "demo")
        self.assertEqual(read_form.read_request(body, 2.0, 10.0), ("Add tags\nto notes", 2.0))

    def test_a_cap_is_carried_and_an_explanation_above_the_form_does_not_leak_into_it(self):
        body = "Why it failed: ...\n\n---\n\n" + render_form.form_body("demo", "do it", "1.50")
        self.assertEqual(read_form.read_request(body, 2.0, 10.0), ("do it", 1.5))


if __name__ == "__main__":
    unittest.main()
