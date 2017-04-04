import sublime
import sublime_plugin
import sys
import os
import re
import json
import subprocess
from subprocess import Popen
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "dependences"))
from nltk.corpus import wordnet as wn

if sublime.version() < '3000':
    # for now, FancyWord only supports SublimeText 3
    _ST3 = False
else:
    _ST3 = True
    from urllib.request import Request
    from urllib.request import urlopen
    from urllib.error import HTTPError, URLError

package_folder = os.path.dirname(__file__)
# word2vec_api_server process
p = None


def start_subproc(c):
    global p
    p = Popen(c, stdin=subprocess.PIPE,
              stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def plugin_loaded() -> None:
    print('FancyWord loaded')
    if not os.path.exists(os.path.join(package_folder, 'Main.sublime-menu')):
        template_file = os.path.join(
            package_folder, 'templates', 'Main.sublime-menu.tpl'
        )
        with open(template_file, 'r', encoding='utf8') as tplfile:
            template = Template(tplfile.read())

        menu_file = os.path.join(package_folder, 'Main.sublime-menu')
        with open(menu_file, 'w', encoding='utf8') as menu:
            menu.write(template.safe_substitute({
                'package_folder': os.path.basename(package_folder)
            }))


def plugin_unloaded() -> None:
    if p and not p.poll():
        p.terminate()

# deprecated method, because gensim can't be run in plugin (Python3.3.6)


def word2vec_topn_inproc(w, n):
    from gensim.models.keyedvectors import KeyedVectors as k
    from gensim.models.word2vec import Word2Vec as w
    model = k.load_word2vec_format(
        s['word2vec']['pretrained_word2vec_model'], binary=True)
    try:
        tops = model.most_similar_cosmul(positive=[w], topn=n)
        tops = map(lambda x: x[0], tops)
        return list(tops)[:n]
    except KeyError as e:
        return []


def word2vec_topn_outproc(w, n):
    url = "http://127.0.0.1:5000/word2vec/most_similar?positive={}&topn={}".format(
        w, n)
    req = Request(url, None)
    try:
        page = urlopen(req)
        html = page.read().decode()
        page.close()
        words_distances = json.loads(html)
        words = list(map(lambda x: x[0], words_distances))
        return words
    except HTTPError:
        return []
    except URLError:
        raise


def wordnet_topn(w, n, lang):
    rst = []
    a = [ss for ss in wn.synsets(w, lang=lang)]
    for ai in a:
        name = ai.name().split('.')[0]
        if name not in rst:
            rst.append(name)
    b = [sim for ai in a for sim in ai.similar_tos()]
    for bi in b:
        name = bi.name().split('.')[0]
        if name not in rst:
            rst.append(name)
    if w in rst:
        rst.remove(w)
    return rst[:n]


class FancyWordCommand(sublime_plugin.TextCommand):

    def __init__(self, view):
        sublime_plugin.TextCommand.__init__(self, view)
        s = sublime.load_settings("FancyWord.sublime-settings")
        self.topn = int(s.get('topn', 10))
        self.lang = s.get('language', 'eng')
        self.word2vec_setting = s.get('word2vec', {})
        self.word2vec_enabled = self.word2vec_setting.get('enabled', False)
        self.word2vec_python_path = self.word2vec_setting.get(
            'python_path', 'python')
        self.word2vec_model = self.word2vec_setting.get(
            'pretrained_word2vec_model', '')
        self.word2vec_port = self.word2vec_setting.get('port', 5000)
        self.wordnet_enabled = s.get('wordnet', {}).get('enabled', True)
        # when word2vec-api server is dead, restart it
        if self.word2vec_enabled and (not p or p.poll()):
            # ['/usr/local/bin/python', '/Users/easton/Downloads/word2vec-api/word2vec-api.py', '--model', '~/Downloads/deps.words.bin', '--binary', 'true']
            print('FancyWord: word2vec-api server will be started')
            word2vec_api_file_path = os.path.join(
                package_folder, 'dependences/word2vec-api.py')
            self.word2vec_api_command = [self.word2vec_python_path, word2vec_api_file_path,
                                         '--model', self.word2vec_model,
                                         '--binary', 'true',
                                         '--port', str(self.word2vec_port)]
            start_subproc(self.word2vec_api_command)

    def run(self, edit):
        self.selection = self.view.sel()
        self.pos = self.view.sel()[0]
        if self.view.sel()[0].a == self.view.sel()[0].b:
            self.view.run_command("expand_selection", {"to": "word"})

        phrase = self.view.substr(self.selection[0]).lower()
        if not phrase:
            return  # nothing selected

        try:
            word2vec_rst = word2vec_topn_outproc(phrase, self.topn)
        except URLError:
            print('FancyWord: word2vec-api server can\'t be reachable')
            print('FancyWord: Will try to start word2vec-api server next time')
            word2vec_rst = []

        wordnet_rst = wordnet_topn(phrase, self.topn, self.lang)
        self.suggestions = []
        self.index_suggestions = []
        if word2vec_rst:
            self.index_suggestions += ['{}: {}'.format(idx + 1, sug) + (''.join(
                [' ' * 4, '=' * 4, ' Word2Vec results:']) if idx == 0 else '') for idx, sug in enumerate(word2vec_rst)]
            self.suggestions += word2vec_rst
        len_word2vec_sug = len(word2vec_rst)
        if wordnet_rst:
            self.index_suggestions += ['{}: {}'.format(idx + len_word2vec_sug + 1, sug) + (''.join(
                [' ' * 4, '=' * 4, ' Wordnet results:']) if idx == 0 else '') for idx, sug in enumerate(wordnet_rst)]
            self.suggestions += wordnet_rst
        if self.suggestions:
            self.view.window().show_quick_panel(self.index_suggestions,
                                                self.on_done,
                                                sublime.MONOSPACE_FONT)
        else:
            sublime.status_message("FancyWord: can't find similar words for {}!".format(phrase))
            self.on_done(-1)

    def on_done(self, index):
        if (index == -1):
            self.view.sel().clear()
            if not _ST3:
                self.view.sel().add(sublime.Region(long(self.pos.a), long(self.pos.b)))
            else:
                self.view.sel().add(sublime.Region(self.pos.a, self.pos.b))
            return
        self.view.run_command("insert_my_text", {"args": {'text': self.suggestions[index],
                                                          'posa': self.pos.a, 'posb': self.pos.b}})


class LookUpWordCommand(sublime_plugin.TextCommand):
    # def __init__(self, view):
    #     sublime_plugin.TextCommand.__init__(self, view)

    def run(self, edit):
        self.selection = self.view.sel()
        self.pos = self.view.sel()[0]
        if self.view.sel()[0].a == self.view.sel()[0].b:
            self.view.run_command("expand_selection", {"to": "word"})

        phrase = self.view.substr(self.selection[0]).lower()
        self.view.sel().clear()
        if not _ST3:
            self.view.sel().add(sublime.Region(long(self.pos.a), long(self.pos.b)))
        else:
            self.view.sel().add(sublime.Region(self.pos.a, self.pos.b))

        if not phrase:
            return  # nothing selected
        s = sublime.load_settings("FancyWord.sublime-settings") or {}
        lang = s.get('language', 'eng')
        definitions = {w.name(): w.definition() for w in wn.synsets(phrase, lang=lang)}
        if not definitions:
            sublime.status_message("FancyWord: can't find definition words for {}!".format(phrase))
            return
        self.definitions = '<br>'.join(
            ['<u>' + w + '</u>: ' + d for w, d in definitions.items()])
        if int(sublime.version()) >= 3070:
            self.view.show_popup(self.definitions)
        else:
            self.print_doc(edit)

    def print_popup(self, edit) -> None:
        """Show message in a popup
        """

        dlines = self.definitions.splitlines()
        name = dlines[0]
        docstring = ''.join(dlines[1:])
        content = {'name': name, 'content': docstring}
        self.definitions = None
        self.view.show_tooltip(content)

    def print_doc(self, edit: sublime.Edit) -> None:
        """Print the documentation string into a Sublime Text panel
        """

        doc_panel = self.view.window().create_output_panel(
            'anaconda_documentation'
        )

        doc_panel.set_read_only(False)
        region = sublime.Region(0, doc_panel.size())
        doc_panel.erase(edit, region)
        doc_panel.insert(edit, 0, self.definitions)
        self.definitions = None
        doc_panel.set_read_only(True)
        doc_panel.show(0)
        self.view.window().run_command(
            'show_panel', {'panel': 'output.anaconda_documentation'}
        )


class InsertMyText(sublime_plugin.TextCommand):
    def run(self, edit, args):
        self.view.replace(edit, self.view.sel()[0], args['text'])