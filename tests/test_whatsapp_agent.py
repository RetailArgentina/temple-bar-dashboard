import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta


class TestSessionManagement:
    def test_get_session_retorna_lista_vacia_si_no_existe(self):
        from whatsapp_agent import get_session

        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        result = get_session(mock_db, "whatsapp:+549111111111")
        assert result == []

    def test_get_session_retorna_lista_vacia_si_expirada(self):
        from whatsapp_agent import get_session

        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "messages": [{"role": "user", "content": "hola"}],
            "last_activity": datetime.utcnow() - timedelta(hours=3),
            "user_name": "Darwin",
            "role": "admin",
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        result = get_session(mock_db, "whatsapp:+549111111111")
        assert result == []

    def test_get_session_retorna_mensajes_si_vigente(self):
        from whatsapp_agent import get_session

        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        messages = [{"role": "user", "content": "hola"}]
        mock_doc.to_dict.return_value = {
            "messages": messages,
            "last_activity": datetime.utcnow() - timedelta(minutes=10),
            "user_name": "Darwin",
            "role": "admin",
        }
        mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        result = get_session(mock_db, "whatsapp:+549111111111")
        assert result == messages

    def test_save_session_guarda_maximo_10_mensajes(self):
        from whatsapp_agent import save_session

        mock_db = MagicMock()
        messages = [{"role": "user", "content": str(i)} for i in range(15)]

        save_session(mock_db, "whatsapp:+549111111111", messages, "Darwin", "admin")

        saved_data = mock_db.collection.return_value.document.return_value.set.call_args[0][0]
        assert len(saved_data["messages"]) == 10
        assert saved_data["messages"][0]["content"] == "5"


class TestAccessControl:
    def _config(self):
        return {
            "users": [
                {"phone": "whatsapp:+549111111111", "name": "Darwin", "role": "admin"},
                {"phone": "whatsapp:+549222222222", "name": "Gerente", "role": "viewer"},
            ]
        }

    def test_admin_es_reconocido(self):
        from whatsapp_agent import get_user
        user = get_user("whatsapp:+549111111111", self._config())
        assert user is not None
        assert user["role"] == "admin"

    def test_viewer_es_reconocido(self):
        from whatsapp_agent import get_user
        user = get_user("whatsapp:+549222222222", self._config())
        assert user is not None
        assert user["role"] == "viewer"

    def test_numero_desconocido_retorna_none(self):
        from whatsapp_agent import get_user
        user = get_user("whatsapp:+549999999999", self._config())
        assert user is None


class TestAgentLoop:
    def test_responde_texto_cuando_no_usa_tools(self):
        from whatsapp_agent import run_agent

        mock_anthropic = MagicMock()
        mock_bq = MagicMock()

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Hola, soy el agente retail."
        mock_response.content = [mock_text_block]
        mock_anthropic.messages.create.return_value = mock_response

        text, new_history = run_agent(
            user_message="hola",
            history=[],
            user_role="admin",
            bq_client=mock_bq,
            anthropic_client=mock_anthropic,
        )

        assert text == "Hola, soy el agente retail."
        assert len(new_history) == 2

    def test_viewer_recibe_tools_reducidas(self):
        from whatsapp_agent import run_agent

        mock_anthropic = MagicMock()
        mock_bq = MagicMock()

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_text = MagicMock()
        mock_text.type = "text"
        mock_text.text = "ok"
        mock_response.content = [mock_text]
        mock_anthropic.messages.create.return_value = mock_response

        run_agent("hola", [], "viewer", mock_bq, mock_anthropic)

        call_kwargs = mock_anthropic.messages.create.call_args[1]
        tool_names = [t["name"] for t in call_kwargs.get("tools", [])]
        assert "query_product" not in tool_names
