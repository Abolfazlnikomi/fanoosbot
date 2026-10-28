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
