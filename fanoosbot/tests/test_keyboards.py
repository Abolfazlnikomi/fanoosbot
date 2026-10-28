import unittest
from unittest.mock import patch

import bot


class InlineKeyboardTests(unittest.TestCase):
    def setUp(self):
        bot.STATES.clear()
        self.addCleanup(bot.STATES.clear)

    def test_form_prompt_has_cancel_button(self):
        bot.STATES[10] = ["identity_upload", None]
        with patch.object(bot, "api") as api:
            bot.send_message(10, "upload")
        self.assertEqual(api.call_args.kwargs["reply_markup"], {
            "inline_keyboard": [[{"text": "✖️ انصراف", "callback_data": "cancel"}]]
        })

    def test_admin_panel_uses_vertical_inline_keyboard(self):
        with patch.object(bot, "api") as api, patch.object(bot, "is_admin", return_value=True), \
                patch.object(bot, "get_setting_int", return_value=4):
            bot.admin_panel(10, 20)
        self.assertEqual(api.call_args.args[0], "editMessageText")
        rows = api.call_args.kwargs["reply_markup"]["inline_keyboard"]
        self.assertTrue(all(len(row) == 1 for row in rows))
        actions = [row[0]["callback_data"] for row in rows]
        self.assertIn("a:identity", actions)
        self.assertIn("a:discounts", actions)

    def test_admin_submenu_overrides_explicit_row_width(self):
        markup = bot.make_keyboard([
            ("confirm", "a:rmac:42"), ("cancel", "a:admins")
        ], row_width=2)
        self.assertEqual([len(row) for row in markup["inline_keyboard"]], [1, 1])

    def test_user_keyboard_keeps_requested_row_width(self):
        markup = bot.make_keyboard([("one", "s1"), ("two", "s2")], row_width=2)
        self.assertEqual(len(markup["inline_keyboard"][0]), 2)

    def test_admin_command_removes_legacy_reply_keyboard(self):
        with patch.object(bot, "has_access", return_value=True), \
                patch.object(bot, "is_admin", return_value=True), \
                patch.object(bot, "register_user"), patch.object(bot, "api") as api, \
                patch.object(bot, "admin_panel") as panel:
            bot.handle_message(10, "/admin", "user")
        self.assertEqual(api.call_args.kwargs["reply_markup"], {"remove_keyboard": True})
        panel.assert_called_once_with(10)

    def test_existing_keyboard_is_preserved(self):
        bot.STATES[10] = ["quiz", {}]
        markup = {"inline_keyboard": [[{"text": "answer", "callback_data": "q1"}]]}
        with patch.object(bot, "api") as api:
            bot.send_message(10, "question", markup)
        self.assertEqual(api.call_args.kwargs["reply_markup"], markup)

    def test_edit_without_message_sends_new_message(self):
        with patch.object(bot, "send_message") as send:
            bot.edit_message(10, None, "panel", {})
        send.assert_called_once_with(10, "panel", {})

    def callback(self, data, admin=True):
        with patch.object(bot, "has_access", return_value=True), \
                patch.object(bot, "is_admin", return_value=admin), \
                patch.object(bot, "is_owner", return_value=admin), \
                patch.object(bot, "rate_ok", return_value=True), \
                patch.object(bot, "answer_callback"):
            bot.handle_callback(10, data, "callback", 20, "user")

    def test_cancel_upload_returns_to_identity_panel(self):
        bot.STATES[10] = ["identity_upload", None]
        with patch.object(bot, "handle_identity_callback") as panel:
            self.callback("cancel")
        self.assertNotIn(10, bot.STATES)
        panel.assert_called_once_with(10, "a:identity", 20)

    def test_admin_removal_requires_confirmation(self):
        with patch.object(bot, "q") as query, patch.object(bot, "edit_message") as edit:
            self.callback("a:rma:42")
        query.assert_not_called()
        buttons = edit.call_args.args[3]["inline_keyboard"]
        self.assertEqual(buttons[0][0]["callback_data"], "a:rmac:42")
        self.assertTrue(all(len(row) == 1 for row in buttons))

    def test_non_admin_cannot_confirm_removal(self):
        with patch.object(bot, "q") as query:
            self.callback("a:rmac:42", admin=False)
        query.assert_not_called()

    def test_confirmed_removal_deletes_admin(self):
        with patch.object(bot, "q") as query, patch.object(bot, "send_message"), \
                patch.object(bot, "admins_panel"):
            self.callback("a:rmac:42")
        query.assert_called_once_with("DELETE FROM admins WHERE chat_id=?", (42,))


if __name__ == "__main__":
    unittest.main()
