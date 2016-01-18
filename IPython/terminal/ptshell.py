"""IPython terminal interface using prompt_toolkit in place of readline"""
from __future__ import print_function

from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.py3compat import PY3
from traitlets import Bool, Unicode, Dict

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.enums import DEFAULT_BUFFER
from prompt_toolkit.filters import HasFocus, HasSelection
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.shortcuts import create_prompt_application, create_eventloop
from prompt_toolkit.interface import CommandLineInterface
from prompt_toolkit.key_binding.manager import KeyBindingManager
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.key_binding.bindings.vi import ViStateFilter
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.lexers import PygmentsLexer
from prompt_toolkit.styles import PygmentsStyle

from pygments.styles import get_style_by_name
from pygments.lexers import Python3Lexer, PythonLexer
from pygments.token import Token

from .pt_inputhooks import get_inputhook_func


class IPythonPTCompleter(Completer):
    """Adaptor to provide IPython completions to prompt_toolkit"""
    def __init__(self, ipy_completer):
        self.ipy_completer = ipy_completer

    def get_completions(self, document, complete_event):
        if not document.current_line.strip():
            return

        used, matches = self.ipy_completer.complete(
                            line_buffer=document.current_line,
                            cursor_pos=document.cursor_position_col
        )
        start_pos = -len(used)
        for m in matches:
            yield Completion(m, start_position=start_pos)

class PTInteractiveShell(InteractiveShell):
    colors_force = True

    pt_cli = None

    vi_mode = Bool(False, config=True,
        help="Use vi style keybindings at the prompt",
    )

    highlighting_style = Unicode('', config=True,
        help="The name of a Pygments style to use for syntax highlighting"
    )

    highlighting_style_overrides = Dict(config=True,
        help="Override highlighting format for specific tokens"
    )

    def get_prompt_tokens(self, cli):
        return [
            (Token.Prompt, 'In ['),
            (Token.PromptNum, str(self.execution_count)),
            (Token.Prompt, ']: '),
        ]

    def get_continuation_tokens(self, cli, width):
        return [
            (Token.Prompt, (' ' * (width - 2)) + ': '),
        ]

    def init_prompt_toolkit_cli(self):
        kbmanager = KeyBindingManager.for_prompt(enable_vi_mode=self.vi_mode)
        insert_mode = ViStateFilter(kbmanager.get_vi_state, InputMode.INSERT)
        # Ctrl+J == Enter, seemingly
        @kbmanager.registry.add_binding(Keys.ControlJ,
                            filter=(HasFocus(DEFAULT_BUFFER)
                                    & ~HasSelection()
                                    & insert_mode
                                   ))
        def _(event):
            b = event.current_buffer
            if not b.document.on_last_line:
                b.newline()
                return

            status, indent = self.input_splitter.check_complete(b.document.text)

            if (status != 'incomplete') and b.accept_action.is_returnable:
                b.accept_action.validate_and_handle(event.cli, b)
            else:
                b.insert_text('\n' + (' ' * (indent or 0)))

        @kbmanager.registry.add_binding(Keys.ControlC)
        def _(event):
            event.current_buffer.reset()

        # Pre-populate history from IPython's history database
        history = InMemoryHistory()
        last_cell = u""
        for _, _, cell in self.history_manager.get_tail(self.history_load_length,
                                                        include_latest=True):
            # Ignore blank lines and consecutive duplicates
            cell = cell.rstrip()
            if cell and (cell != last_cell):
                history.append(cell)

        style_overrides = {
            Token.Prompt: '#009900',
            Token.PromptNum: '#00ff00 bold',
        }
        if self.highlighting_style:
            style_cls = get_style_by_name(self.highlighting_style)
        else:
            style_cls = get_style_by_name('default')
            # The default theme needs to be visible on both a dark background
            # and a light background, because we can't tell what the terminal
            # looks like. These tweaks to the default theme help with that.
            style_overrides.update({
                Token.Number: '#007700',
                Token.Operator: 'noinherit',
                Token.String: '#BB6622',
                Token.Name.Function: '#2080D0',
                Token.Name.Class: 'bold #2080D0',
                Token.Name.Namespace: 'bold #2080D0',
            })
        style_overrides.update(self.highlighting_style_overrides)
        style = PygmentsStyle.from_defaults(pygments_style_cls=style_cls,
                                            style_dict=style_overrides)

        app = create_prompt_application(multiline=True,
                            lexer=PygmentsLexer(Python3Lexer if PY3 else PythonLexer),
                            get_prompt_tokens=self.get_prompt_tokens,
                            get_continuation_tokens=self.get_continuation_tokens,
                            key_bindings_registry=kbmanager.registry,
                            history=history,
                            completer=IPythonPTCompleter(self.Completer),
                            enable_history_search=True,
                            style=style,
        )

        self.pt_cli = CommandLineInterface(app,
                           eventloop=create_eventloop(self.inputhook))

    def __init__(self, *args, **kwargs):
        super(PTInteractiveShell, self).__init__(*args, **kwargs)
        self.init_prompt_toolkit_cli()
        self.keep_running = True

    def ask_exit(self):
        self.keep_running = False

    def interact(self):
        while self.keep_running:
            print(self.separate_in, end='')
            try:
                document = self.pt_cli.run()
            except EOFError:
                if self.ask_yes_no('Do you really want to exit ([y]/n)?','y','n'):
                    self.ask_exit()

            else:
                if document:
                    self.run_cell(document.text, store_history=True)

    _inputhook = None
    def inputhook(self, context):
        if self._inputhook is not None:
            self._inputhook(context)

    def enable_gui(self, gui=None):
        if gui:
            self._inputhook = get_inputhook_func(gui)
        else:
            self._inputhook = None

if __name__ == '__main__':
    PTInteractiveShell.instance().interact()
