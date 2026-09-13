import threading

from config.app_settings import get_agent_name, get_language
from environment import get_environment_context
from llm.ollama_client import chat_with_tools
from memory.memory_manager import MemoryManager
from security.permissions import is_admin
from tools.tool_registry import execute_pending_action, execute_tool
from web.database import save_web_message


MAX_TOOL_STEPS = 6


SYSTEM_PROMPT = """
You are a local AI Agent running on the user's computer.

Understand the user's request, choose tools when needed, inspect real tool results, and continue planning until the task is actually complete.

GENERAL RULES:
- Do not use tools for normal conversation unless they are needed.
- Never claim that an action succeeded without a successful tool result.
- Never treat a failed tool call as success.
- Never invent information that is not present in a tool result.
- A helper tool completing one step does not mean the user's full task is complete.
- Never attempt to bypass PermissionError or another security restriction.
- A tool selected by the user in an interface is a strong intent signal, but you still decide the necessary tool sequence.
- Keep final responses concise unless the user requests more detail.
- Reply in the language used in the user's latest request.
- If the latest request is too short or its language is unclear, use the configured default response language.
- Tool results may be written in English. Translate and explain them in the language of the user's latest request.

FILES:
- Use create_file to create a new file.
- If a new file should already contain content, pass that content directly to create_file.
- Do not create an empty file and then call write_file unless that is actually necessary.
- Use write_file to change an existing text file.
- Use mode="append" when the user asks to append or add content to the end.
- Use mode="overwrite" when existing content must be replaced.
- Use read_file to read an allowed file.
- Use search_files when the real path is uncertain.
- search_files accepts query, extension and directory. Do not use path as the directory argument.
- Use list_directory to list a directory.
- Use open_path to open a file or folder.
- Use manage_file only for delete, move and rename operations.
- Never invent file paths.
- If search_files returns one clear result, use its real path for the next operation.
- If several possible files are returned, do not randomly choose one.
- Do not attempt to access protected or sensitive files.
- File confirmation is enforced by Python. Never assume the user confirmed an operation.

TELEGRAM:
- Use telegram_send_message to send a Telegram text message.
- Use send_file to send a local file through Telegram.
- If the file path is unknown, use search_files first.
- Never say a Telegram message or file was sent unless the sending tool succeeded.

DOCUMENTS:
- Use search_documents for semantic search over indexed documents.
- Phrases such as "this document", "this PDF" or "the document I uploaded" may refer to the latest Web document.
- Use the source parameter when searching one specific indexed document.
- Do not use source for requests that clearly mean all indexed documents.
- Never invent information that is not present in document search results.

HISTORY:
- Use get_recent_messages when the user asks about conversation history.
- History access is enforced by Python permissions.
- Never attempt to expose another user's history.
- Use source when the user explicitly names a history source.
- Use limit when the user explicitly requests a number of messages.

MATH:
- Use calculate for mathematical calculations.
""".strip()


def tool(name, description, properties, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


TOOLS = [
    tool(
        "calculate",
        "Calculate a mathematical expression.",
        {
            "expression": {
                "type": "string",
            }
        },
        ["expression"],
    ),
    tool(
        "search_documents",
        "Search indexed local documents semantically.",
        {
            "query": {
                "type": "string",
            },
            "source": {
                "type": "string",
                "description": (
                    "Optional document filename when the search must be "
                    "restricted to one indexed document."
                ),
            },
            "top_k": {
                "type": "integer",
            },
        },
        ["query"],
    ),
    tool(
        "telegram_send_message",
        "Send a real text message to the authorized Telegram account.",
        {
            "message": {
                "type": "string",
            }
        },
        ["message"],
    ),
    tool(
        "create_file",
        "Create a new file with optional initial content.",
        {
            "path": {
                "type": "string",
            },
            "content": {
                "type": "string",
            },
        },
        ["path", "content"],
    ),
    tool(
        "write_file",
        "Modify an existing text file or append content to it.",
        {
            "path": {
                "type": "string",
            },
            "content": {
                "type": "string",
            },
            "mode": {
                "type": "string",
                "enum": [
                    "overwrite",
                    "append",
                ],
            },
        },
        [
            "path",
            "content",
            "mode",
        ],
    ),
    tool(
        "read_file",
        "Read the content of an allowed local file.",
        {
            "path": {
                "type": "string",
            }
        },
        ["path"],
    ),
    tool(
        "search_files",
        "Recursively search for files in allowed locations.",
        {
            "query": {
                "type": "string",
            },
            "extension": {
                "type": "string",
            },
            "directory": {
                "type": "string",
            },
        },
    ),
    tool(
        "list_directory",
        "List the contents of an allowed directory.",
        {
            "path": {
                "type": "string",
            }
        },
        ["path"],
    ),
    tool(
        "open_path",
        "Open an allowed file or directory on the local Windows computer.",
        {
            "path": {
                "type": "string",
            }
        },
        ["path"],
    ),
    tool(
        "manage_file",
        "Delete, move or rename an allowed file.",
        {
            "action": {
                "type": "string",
                "enum": [
                    "delete",
                    "move",
                    "rename",
                ],
            },
            "path": {
                "type": "string",
            },
            "destination": {
                "type": "string",
            },
        },
        [
            "action",
            "path",
        ],
    ),
    tool(
        "send_file",
        "Send an allowed local file through Telegram.",
        {
            "path": {
                "type": "string",
            }
        },
        ["path"],
    ),
    tool(
        "get_recent_messages",
        "Read conversation history that the current identity is allowed to access.",
        {
            "source": {
                "type": "string",
                "enum": [
                    "terminal",
                    "telegram",
                    "web",
                ],
            },
            "limit": {
                "type": "integer",
            },
        },
    ),
]


WEB_TOOL_SELECTIONS = {
    "create": ("create_file", {}),
    "read": ("read_file", {}),
    "write": ("write_file", {}),
    "search-files": ("search_files", {}),
    "list": ("list_directory", {}),
    "open": ("open_path", {}),
    "rename": ("manage_file", {"action": "rename"}),
    "move": ("manage_file", {"action": "move"}),
    "delete": ("manage_file", {"action": "delete"}),
    "telegram-message": ("telegram_send_message", {}),
    "telegram-file": ("send_file", {}),
    "rag": ("search_documents", {}),
    "history": ("get_recent_messages", {}),
}


TOOL_HELPERS = {
    "read_file": {"search_files"},
    "write_file": {"search_files"},
    "open_path": {"search_files"},
    "manage_file": {"search_files"},
    "send_file": {"search_files"},
}


FILE_TOOLS = {
    "create_file",
    "write_file",
    "read_file",
    "search_files",
    "list_directory",
    "open_path",
    "manage_file",
    "send_file",
}


IMMEDIATE_TOOLS = {
    "send_file",
    "get_recent_messages",
}


class Agent:
    def __init__(self):
        self.memory = MemoryManager()
        self.lock = threading.Lock()
        self.pending_actions = {}
        self.contexts = {}

    def reset_conversation(
        self,
        source="terminal",
        user_id=None,
    ):
        with self.lock:
            self.contexts.pop(
                self._context_key(
                    source,
                    user_id,
                ),
                None,
            )
            self.pending_actions.pop(
                self._pending_key(
                    source,
                    user_id,
                ),
                None,
            )

    def _language(self):
        return (
            "tr"
            if get_language() == "tr"
            else "en"
        )

    def _text(self, tr, en):
        return (
            tr
            if self._language() == "tr"
            else en
        )

    def _system_prompt(self):
        language = (
            "Turkish"
            if self._language() == "tr"
            else "English"
        )

        return (
            SYSTEM_PROMPT
            + "\n\n"
            + f"Configured Agent name: {get_agent_name()}\n"
            + f"Default response language: {language}"
        )

    def _pending_key(self, source, user_id):
        if source in {
            "web",
            "telegram",
        }:
            return source, user_id

        return source, None

    def _context_key(self, source, user_id):
        if (
            source == "web"
            and user_id is None
        ):
            return None

        if source in {
            "web",
            "telegram",
        }:
            return source, user_id

        return source, None

    def _get_messages(self, source, user_id):
        key = self._context_key(
            source,
            user_id,
        )

        base = {
            "role": "system",
            "content": self._system_prompt(),
        }

        if key is None:
            return [base]

        if key not in self.contexts:
            self.contexts[key] = [
                base
            ]

        return self.contexts[key]

    def _user_role(self, source, user_id):
        if (
            user_id is not None
            and source in {
                "web",
                "telegram",
            }
        ):
            if is_admin(
                source,
                user_id,
            ):
                return "user_admin"

            return f"user_{user_id}"

        return "user"

    def _save_user_message(
        self,
        source,
        user_id,
        role,
        content,
    ):
        if source == "web":
            if user_id is not None:
                save_web_message(
                    user_id,
                    role,
                    content,
                )

            return

        self.memory.save_message(
            role,
            source,
            content,
        )

    def _save_response(
        self,
        source,
        user_id,
        response,
    ):
        response = str(response)

        if source == "web":
            if user_id is not None:
                save_web_message(
                    user_id,
                    "assistant",
                    response,
                )

            return response

        self.memory.save_message(
            "assistant",
            source,
            response,
        )

        return response

    def _format_confirmation(
        self,
        action,
        details=False,
    ):
        path = action.get(
            "path",
            "",
        )

        title = action.get(
            "title"
        ) or self._text(
            "Bir dosya işlemi gerçekleştirilecek.",
            "A file operation will be performed.",
        )

        lines = [
            title,
            "",
            self._text(
                f"Dosya: {path}",
                f"File: {path}",
            ),
        ]

        destination = action.get(
            "destination"
        )

        if destination:
            lines += [
                "",
                self._text(
                    f"Hedef: {destination}",
                    f"Destination: {destination}",
                ),
            ]

        if (
            details
            and action.get("action")
            == "write_file"
        ):
            old_preview = (
                action.get(
                    "old_preview",
                    "",
                )
                or self._text(
                    "[boş]",
                    "[empty]",
                )
            )

            new_preview = (
                action.get(
                    "new_preview",
                    "",
                )
                or self._text(
                    "[boş]",
                    "[empty]",
                )
            )

            lines += [
                "",
                self._text(
                    "Mevcut içerik:",
                    "Current content:",
                ),
                old_preview,
                "",
                self._text(
                    "Yeni içerik:",
                    "New content:",
                ),
                new_preview,
            ]

        lines += [
            "",
            self._text(
                "Onaylıyor musunuz? (y/n)",
                "Do you confirm? (y/n)",
            ),
        ]

        return "\n".join(
            lines
        )

    def _handle_pending_action(
        self,
        message,
        source,
        user_id,
    ):
        key = self._pending_key(
            source,
            user_id,
        )

        action = self.pending_actions.get(
            key
        )

        if not action:
            return None

        text = (
            str(message)
            .strip()
            .lower()
        )

        yes = {
            "y",
            "yes",
            "evet",
            "onayla",
            "onaylıyorum",
            "onayliyorum",
            "confirm",
        }

        no = {
            "n",
            "no",
            "hayır",
            "hayir",
            "iptal",
            "cancel",
            "vazgeç",
            "vazgec",
        }

        details = {
            "ne değişiyor",
            "ne değişiyor?",
            "ne degisiyor",
            "ne degisiyor?",
            "ne değişecek",
            "ne değişecek?",
            "ne degisecek",
            "ne degisecek?",
            "değişiklik ne",
            "degisiklik ne",
            "göster",
            "goster",
            "detay",
            "detayları göster",
            "detaylari goster",
            "details",
            "show details",
            "what changes",
            "what will change",
        }

        if text in yes:
            self.pending_actions.pop(
                key,
                None,
            )

            try:
                return execute_pending_action(
                    action,
                    source=source,
                    user_id=user_id,
                )

            except PermissionError:
                return self._text(
                    "Bu işlem güvenlik nedeniyle uygulanamadı.",
                    "The operation was blocked by security rules.",
                )

            except Exception as error:
                print(
                    "[Agent] Pending action error: "
                    f"{type(error).__name__}"
                )

                return self._text(
                    "Bekleyen işlem uygulanamadı.",
                    "The pending operation could not be completed.",
                )

        if text in no:
            self.pending_actions.pop(
                key,
                None,
            )

            return self._text(
                "İşlem iptal edildi.",
                "The operation was cancelled.",
            )

        if text in details:
            return self._format_confirmation(
                action,
                details=True,
            )

        return self._text(
            (
                "Bekleyen bir dosya işlemi var.\n\n"
                "Onaylamak için y/yes/evet, iptal etmek için "
                "n/no/hayır yazın.\n\n"
                'Değişikliği görmek için "ne değişiyor?" yazabilirsiniz.'
            ),
            (
                "A file operation is waiting for confirmation.\n\n"
                "Type y/yes to confirm or n/no to cancel.\n\n"
                'Type "show details" to review the change.'
            ),
        )

    def _looks_like_file_request(
        self,
        message,
    ):
        text = str(
            message
        ).lower()

        extensions = {
            ".txt",
            ".pdf",
            ".docx",
            ".xlsx",
            ".pptx",
            ".csv",
            ".json",
            ".py",
            ".md",
            ".log",
            ".jpg",
            ".jpeg",
            ".png",
            ".zip",
        }

        actions = {
            "oluştur",
            "olustur",
            "yarat",
            "yaz",
            "ekle",
            "değiştir",
            "degistir",
            "oku",
            "aç",
            "ac",
            "bul",
            "ara",
            "gönder",
            "gonder",
            "sil",
            "taşı",
            "tasi",
            "yeniden adlandır",
            "adını değiştir",
            "adini degistir",
            "create",
            "write",
            "append",
            "read",
            "open",
            "find",
            "search",
            "send",
            "delete",
            "move",
            "rename",
        }

        return (
            any(
                extension in text
                for extension
                in extensions
            )
            and any(
                action in text
                for action
                in actions
            )
        )

    def _refers_to_current_document(
        self,
        message,
    ):
        text = str(
            message
        ).lower()

        references = {
            "bu belge",
            "bu belgede",
            "bu doküman",
            "bu dokümanda",
            "bu dokuman",
            "bu dokumanda",
            "bu pdf",
            "yüklediğim belge",
            "yukledigim belge",
            "yüklediğim dosya",
            "yukledigim dosya",
            "az önce yüklediğim",
            "az once yukledigim",
            "this document",
            "this pdf",
            "uploaded document",
            "document i uploaded",
            "file i uploaded",
        }

        return any(
            reference in text
            for reference
            in references
        )

    def _is_general_document_search(
        self,
        message,
    ):
        text = str(
            message
        ).lower()

        references = {
            "belgelerimde",
            "belgelerim",
            "tüm belgelerde",
            "tum belgelerde",
            "tüm belgelerimde",
            "tum belgelerimde",
            "dokümanlarımda",
            "dokumanlarimda",
            "dokümanlarım",
            "dokumanlarim",
            "tüm dokümanlarda",
            "tum dokumanlarda",
            "my documents",
            "all documents",
            "all my documents",
            "across my documents",
        }

        return any(
            reference in text
            for reference
            in references
        )

    def _selection_context(
        self,
        selected_tool,
    ):
        selection = (
            WEB_TOOL_SELECTIONS.get(
                selected_tool
            )
        )

        if not selection:
            return None, {}, None

        target_tool, fixed_arguments = (
            selection
        )

        helpers = TOOL_HELPERS.get(
            target_tool,
            set(),
        )

        helper_text = (
            ", ".join(
                sorted(helpers)
            )
            if helpers
            else "none"
        )

        context = (
            "UI TOOL SELECTION:\n"
            f"The user selected the '{selected_tool}' capability in the UI.\n"
            f"Expected primary tool: {target_tool}.\n"
            f"Allowed helper tools for planning: {helper_text}.\n"
            "The selection is a strong intent signal, not proof of success. "
            "Use required helper steps if necessary and do not claim completion "
            "until the primary operation actually succeeds."
        )

        return (
            target_tool,
            dict(fixed_arguments),
            context,
        )

    def _prepare_arguments(
        self,
        tool_name,
        arguments,
        message,
        document_source,
        target_tool,
        fixed_arguments,
    ):
        arguments = dict(
            arguments or {}
        )

        if (
            tool_name
            == "search_documents"
        ):
            if self._is_general_document_search(
                message
            ):
                arguments.pop(
                    "source",
                    None,
                )

            elif (
                document_source
                and self._refers_to_current_document(
                    message
                )
            ):
                arguments[
                    "source"
                ] = document_source

        if (
            tool_name
            == "get_recent_messages"
        ):
            text = str(
                message
            ).lower()

            if "terminal" in text:
                arguments[
                    "source"
                ] = "terminal"

            elif "telegram" in text:
                arguments[
                    "source"
                ] = "telegram"

            elif "web" in text:
                arguments[
                    "source"
                ] = "web"

            else:
                arguments.pop(
                    "source",
                    None,
                )

        if (
            tool_name == target_tool
            and fixed_arguments
        ):
            arguments.update(
                fixed_arguments
            )

        return arguments

    def _can_receive_environment(
        self,
        source,
        user_id,
    ):
        if source == "terminal":
            return True

        if (
            source in {
                "web",
                "telegram",
            }
            and user_id is not None
        ):
            return is_admin(
                source,
                user_id,
            )

        return False

    def _build_user_message(
        self,
        message,
        selected_tool,
        document_source,
        target_tool,
        selection_context,
        source,
        user_id,
    ):
        parts = []

        if (
            self._can_receive_environment(
                source,
                user_id,
            )
            and (
                self._looks_like_file_request(
                    message
                )
                or target_tool
                in FILE_TOOLS
            )
        ):
            parts.append(
                get_environment_context()
            )

        if (
            source == "web"
            and document_source
            and self._refers_to_current_document(
                message
            )
            and not self._is_general_document_search(
                message
            )
        ):
            parts.append(
                "WEB DOCUMENT CONTEXT:\n"
                f"Latest uploaded document: {document_source}"
            )

        if (
            selected_tool
            and selection_context
        ):
            parts.append(
                selection_context
            )

        parts.append(
            "USER REQUEST:\n"
            + str(message)
        )

        return "\n\n".join(
            parts
        )

    def _execute_tool(
        self,
        tool_name,
        arguments,
        source,
        user_id,
    ):
        try:
            return execute_tool(
                tool_name,
                arguments,
                source=source,
                user_id=user_id,
            )

        except Exception as error:
            print(
                "[Agent] Tool error: "
                f"{tool_name} "
                f"({type(error).__name__})"
            )
            raise

    def _tool_error_message(
        self,
        error,
    ):
        error_name = type(error).__name__

        if isinstance(
            error,
            PermissionError,
        ):
            return (
                "PermissionError: the requested operation was blocked by "
                "the security layer. Do not attempt to bypass the restriction "
                "and do not claim success."
            )

        if error_name == "TelegramDisabledError":
            return (
                "TelegramDisabledError: Telegram integration is disabled "
                "in Settings. Clearly tell the user that Telegram is turned "
                "off. Do not claim that the message or file was sent."
            )

        if error_name == "TelegramConfigurationError":
            return (
                "TelegramConfigurationError: Telegram settings are incomplete "
                "or invalid. Clearly tell the user to configure Telegram from "
                "Settings. Do not claim that the message or file was sent."
            )

        return (
            "Tool call failed with "
            f"{error_name}. "
            "Review the previous results and choose another valid step if "
            "appropriate. Do not invent a successful result."
        )

    def _incomplete_tool_response(self):
        return self._text(
            "Seçilen araç işlemi tamamlanamadı. İşlem gerçekleştirilmedi.",
            "The selected tool operation could not be completed.",
        )

    def _tool_limit_response(self):
        return self._text(
            "Görev için araç adımı sınırına ulaşıldı. İşlem tamamlanamadı.",
            "The tool-step limit was reached before the task could be completed.",
        )

    def run(
        self,
        user_message,
        source="terminal",
        user_id=None,
        selected_tool=None,
        document_source=None,
    ):
        with self.lock:
            message = str(
                user_message
            ).strip()

            if not message:
                return self._text(
                    "Mesaj boş olamaz.",
                    "The message cannot be empty.",
                )

            role = self._user_role(
                source,
                user_id,
            )

            self._save_user_message(
                source,
                user_id,
                role,
                message,
            )

            pending_response = (
                self._handle_pending_action(
                    message,
                    source,
                    user_id,
                )
            )

            if pending_response is not None:
                return self._save_response(
                    source,
                    user_id,
                    pending_response,
                )

            if source not in {"web", "terminal"}:
                selected_tool = None
                document_source = None

            (
                target_tool,
                fixed_arguments,
                selection_context,
            ) = self._selection_context(
                selected_tool
            )

            qwen_message = (
                self._build_user_message(
                    message,
                    selected_tool,
                    document_source,
                    target_tool,
                    selection_context,
                    source,
                    user_id,
                )
            )

            messages = self._get_messages(
                source,
                user_id,
            )

            messages.append(
                {
                    "role": "user",
                    "content": qwen_message,
                }
            )

            target_completed = False
            completion_retries = 0
            tool_steps = 0

            while True:
                result = chat_with_tools(
                    messages,
                    TOOLS,
                )

                assistant_message = result.get(
                    "message",
                    {},
                )

                messages.append(
                    assistant_message
                )

                tool_calls = (
                    assistant_message.get(
                        "tool_calls"
                    )
                    or []
                )

                if not tool_calls:
                    if (
                        target_tool
                        and not target_completed
                    ):
                        if completion_retries >= 2:
                            return self._save_response(
                                source,
                                user_id,
                                self._incomplete_tool_response(),
                            )

                        completion_retries += 1

                        helpers = TOOL_HELPERS.get(
                            target_tool,
                            set(),
                        )

                        helper_text = (
                            ", ".join(
                                sorted(helpers)
                            )
                            if helpers
                            else "none"
                        )

                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "The selected operation is not complete yet. "
                                    f"Primary tool: {target_tool}. "
                                    f"Helper tools: {helper_text}. "
                                    "Review previous tool results and continue with "
                                    "the next necessary step. Do not provide a final "
                                    "success response until the primary operation "
                                    "actually succeeds."
                                ),
                            }
                        )

                        continue

                    return self._save_response(
                        source,
                        user_id,
                        assistant_message.get(
                            "content",
                            "",
                        ),
                    )

                for tool_call in tool_calls:
                    if tool_steps >= MAX_TOOL_STEPS:
                        return self._save_response(
                            source,
                            user_id,
                            self._tool_limit_response(),
                        )

                    tool_steps += 1

                    function = (
                        tool_call.get(
                            "function",
                            {},
                        )
                    )

                    tool_name = function.get(
                        "name"
                    )

                    arguments = function.get(
                        "arguments",
                        {},
                    )

                    if not tool_name:
                        messages.append(
                            {
                                "role": "tool",
                                "content": (
                                    "The tool call does not contain a tool name. "
                                    "Review the task and choose a valid tool."
                                ),
                            }
                        )
                        continue

                    if not isinstance(
                        arguments,
                        dict,
                    ):
                        messages.append(
                            {
                                "role": "tool",
                                "content": (
                                    "Tool arguments must be a JSON object. "
                                    "Correct the parameters and try again."
                                ),
                            }
                        )
                        continue

                    arguments = (
                        self._prepare_arguments(
                            tool_name,
                            arguments,
                            message,
                            document_source,
                            target_tool,
                            fixed_arguments,
                        )
                    )

                    try:
                        tool_result = (
                            self._execute_tool(
                                tool_name,
                                arguments,
                                source,
                                user_id,
                            )
                        )

                    except Exception as error:
                        error_name = type(error).__name__

                        messages.append(
                            {
                                "role": "tool",
                                "content": (
                                    self._tool_error_message(
                                        error
                                    )
                                ),
                            }
                        )

                        if error_name in {
                            "TelegramDisabledError",
                            "TelegramConfigurationError",
                        }:
                            target_completed = True

                        continue

                    if (
                        isinstance(
                            tool_result,
                            dict,
                        )
                        and tool_result.get(
                            "status"
                        )
                        == "confirmation_required"
                    ):
                        key = self._pending_key(
                            source,
                            user_id,
                        )

                        self.pending_actions[
                            key
                        ] = tool_result

                        return self._save_response(
                            source,
                            user_id,
                            self._format_confirmation(
                                tool_result
                            ),
                        )

                    if (
                        target_tool
                        and tool_name
                        == target_tool
                    ):
                        target_completed = True

                    if (
                        tool_name
                        in IMMEDIATE_TOOLS
                        and (
                            not target_tool
                            or tool_name
                            == target_tool
                        )
                    ):
                        return self._save_response(
                            source,
                            user_id,
                            tool_result,
                        )

                    messages.append(
                        {
                            "role": "tool",
                            "content": str(
                                tool_result
                            ),
                        }
                    )
