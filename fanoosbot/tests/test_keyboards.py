import unittest
from unittest.mock import patch

import bot


class InlineKeyboardTests(unittest.TestCase):
    def setUp(self):
        bot.STATES.clear()
        bot.ADMIN_KEYBOARDS.clear()
        self.addCleanup(bot.STATES.clear)
        self.addCleanup(bot.ADMIN_KEYBOARDS.clear)

    def test_form_prompt_has_cancel_button(self):
        bot.STATES[10] = ["identity_upload", None]
        with patch.object(bot, "api") as api, patch.object(bot, "is_admin", return_value=True):
            bot.send_message(10, "upload")
        self.assertEqual(api.call_args.kwargs["reply_markup"], {
            "keyboard": [[{"text": "✖️ انصراف"}]],
            "resize_keyboard": True, "one_time_keyboard": False
        })

    def test_admin_panel_uses_reply_keyboard(self):
        with patch.object(bot, "api") as api, patch.object(bot, "is_admin", return_value=True), \
                patch.object(bot, "get_setting_int", return_value=2):
            bot.admin_panel(10, 20)
        self.assertEqual(api.call_args.args[0], "sendMessage")
        self.assertIn("keyboard", api.call_args.kwargs["reply_markup"])
        self.assertIn("a:identity", bot.ADMIN_KEYBOARDS[10].values())
        self.assertIn("a:discounts", bot.ADMIN_KEYBOARDS[10].values())

    def test_duplicate_labels_have_distinct_actions(self):
        markup = {"inline_keyboard": [[{"text": "item", "callback_data": "a:sec:1"},
                                       {"text": "item", "callback_data": "a:sec:2"}]]}
        result = bot.admin_reply_keyboard(10, markup)
        self.assertEqual(result["keyboard"][0][1]["text"], "item (2)")
        self.assertEqual(bot.ADMIN_KEYBOARDS[10]["item (2)"], "a:sec:2")

    def test_keyboard_action_routes_before_form_input(self):
        bot.ADMIN_KEYBOARDS[10] = {"cancel": "cancel"}
        bot.STATES[10] = ["identity_upload", None]
        with patch.object(bot, "has_access", return_value=True), \
                patch.object(bot, "is_admin", return_value=True), \
                patch.object(bot, "register_user"), patch.object(bot, "handle_callback") as callback, \
                patch.object(bot, "handle_state_message") as state:
            bot.handle_message(10, "cancel", "user")
        callback.assert_called_once_with(10, "cancel", None, None, "user")
        state.assert_not_called()

    def test_user_section_keyboard_is_not_admin_markup(self):
        self.assertFalse(bot.is_admin_markup({"inline_keyboard": [
            [{"text": "section", "callback_data": "s1"}],
            [{"text": "home", "callback_data": "menu"}]]}))

    def test_main_menu_removes_admin_keyboard(self):
        bot.ADMIN_KEYBOARDS[10] = {"back": "menu"}
        with patch.object(bot, "api") as api, patch.object(bot, "child_sections", return_value=[]), \
                patch.object(bot, "get_setting", return_value="1"), \
                patch.object(bot, "get_setting_int", return_value=1), \
                patch.object(bot, "is_admin", return_value=True), \
                patch.object(bot.identity, "discount_sections", return_value=[]):
            bot.show_menu(10)
        self.assertNotIn(10, bot.ADMIN_KEYBOARDS)
        self.assertEqual(api.call_args_list[0].kwargs["reply_markup"], {"remove_keyboard": True})

    def test_revoked_admin_cannot_use_keyboard_action(self):
        bot.ADMIN_KEYBOARDS[10] = {"delete": "a:rmac:42"}
        with patch.object(bot, "has_access", return_value=False), \
                patch.object(bot.identity, "bind", return_value=False), \
                patch.object(bot, "api"), patch.object(bot, "handle_callback") as callback:
            bot.handle_message(10, "delete", "user")
        callback.assert_not_called()
        self.assertNotIn(10, bot.ADMIN_KEYBOARDS)

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
