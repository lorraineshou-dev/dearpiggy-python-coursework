"""Regression checks for safe, complete server-rendered UI and registered artwork."""

from copy import deepcopy
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game import CATALOG, apply_action, new_state
from views import render_page


PAGES = ('welcome', 'home', 'care', 'feelings', 'chat', 'shop', 'growth', 'settings')
TODAY = '2026-11-01'
PAYLOAD = '<img src=x onerror="alert(1)"> & \'quoted\' </script><script>alert(2)</script>'


class Element:
    def __init__(self, tag, attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []
        self.text = ''

    def find(self, tag=None, **attrs):
        matches = []
        for child in self.children:
            if (tag is None or child.tag == tag) and all(child.attrs.get(k) == v for k, v in attrs.items()):
                matches.append(child)
            matches.extend(child.find(tag, **attrs))
        return matches

    def classes(self):
        return self.attrs.get('class', '').split()


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Element('document')
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].text += data

    def find(self, tag=None, **attrs):
        return self.root.find(tag, **attrs)


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.state = new_state(TODAY)
        self.csrf = 'test-csrf-token'

    def render(self, page, **kwargs):
        html = render_page(page, self.state, self.csrf, **kwargs)
        return html, Document(html)

    def act(self, action, **fields):
        return apply_action(self.state, action, fields, today=TODAY)

    def assert_safe_document(self, doc):
        scripts = doc.find('script')
        self.assertEqual([s.attrs.get('src') for s in scripts], ['/static/enhance.js'])
        self.assertTrue(all(not script.text.strip() for script in scripts), 'User values must not enter inline JavaScript')
        for node in doc.find():
            self.assertFalse(any(attr.lower().startswith('on') for attr in node.attrs), node.attrs)
            self.assertNotIn('style', node.attrs, 'Strict CSP must not require inline styles')
            for attribute in ('href', 'src', 'action'):
                value = node.attrs.get(attribute, '')
                self.assertFalse(value.strip().lower().startswith('javascript:'), value)

    def stage(self, doc, identifier='shop-avatar'):
        matches = doc.find('div', id=identifier)
        self.assertEqual(len(matches), 1, 'The main stage must have one avatar')
        return matches[0]

    def test_all_pages_render_in_both_languages_with_working_forms_and_navigation(self):
        paths = {'/', '/care', '/feelings', '/chat', '/shop', '/growth', '/settings'}
        for language in ('zh-CN', 'en'):
            self.state['lang'] = language
            for page in PAGES:
                with self.subTest(language=language, page=page):
                    html, doc = self.render(page)
                    self.assertTrue(html.startswith('<!doctype html>'))
                    self.assertTrue(html.endswith('</html>'))
                    self.assertEqual(doc.find('html')[0].attrs['lang'], language)
                    self.assertEqual(len(doc.find('main', id='main')), 1)
                    self.assertEqual(len(doc.find('h1')), 1)
                    self.assert_safe_document(doc)
                    if page != 'welcome':
                        nav = next(n for n in doc.find('nav') if 'bottom-nav' in n.classes())
                        self.assertEqual({a.attrs['href'] for a in nav.find('a')}, paths)
                        current = nav.find('a', **{'aria-current': 'page'})
                        self.assertEqual(len(current), 1)
                        self.assertEqual(current[0].attrs['href'], '/' if page == 'home' else '/' + page)
                    for form in doc.find('form'):
                        self.assertEqual(form.attrs['method'], 'post')
                        self.assertEqual(form.attrs['action'], '/action')
                        fields = {n.attrs.get('name'): n.attrs.get('value') for n in form.find('input', type='hidden')}
                        self.assertEqual(fields['csrf'], self.csrf)
                        self.assertTrue(fields['action'])
                        self.assertIn(fields['next'], paths)
                        self.assertFalse(form.find('form'), 'Forms must not be nested')

    def test_user_profile_habits_categories_and_journal_are_escaped(self):
        self.state['name'] = PAYLOAD
        self.state['nickname'] = PAYLOAD
        self.state['categories'] = [{'id': 'custom-cat', 'zh': PAYLOAD, 'en': PAYLOAD}]
        self.state['habits'].append({'id': 'custom-habit', 'zh': PAYLOAD, 'en': PAYLOAD,
                                     'category': 'custom-cat', 'icon': '🌱'})
        self.state['journal'] = [{'id': 'journal-test', 'date': TODAY, 'mood': 'calm', 'note': PAYLOAD, 'photo': ''}]
        self.csrf = 'token"<>&\''
        for language in ('zh-CN', 'en'):
            self.state['lang'] = language
            for page in ('home', 'care', 'feelings', 'settings'):
                with self.subTest(page=page, language=language):
                    html, doc = self.render(page)
                    self.assertIn(escape(PAYLOAD, quote=True), html)
                    self.assertNotIn(PAYLOAD, html)
                    self.assert_safe_document(doc)
                    self.assertTrue(all(n.attrs['src'].startswith('/static/') for n in doc.find('img') if 'src' in n.attrs))
                    for field in doc.find('input', name='csrf'):
                        self.assertEqual(field.attrs['value'], self.csrf)
        _, settings = self.render('settings')
        self.assertEqual(settings.find('input', name='name')[0].attrs['value'], PAYLOAD)
        self.assertEqual(settings.find('input', name='nickname')[0].attrs['value'], PAYLOAD)

    def test_chat_escapes_both_speakers_and_errors_without_fake_answers(self):
        chat = [{'role': 'user', 'content': PAYLOAD}, {'role': 'assistant', 'content': PAYLOAD}]
        html, doc = self.render('chat', chat=chat, chat_ready=True, message=PAYLOAD, chat_error=PAYLOAD)
        self.assertEqual(html.count(escape(PAYLOAD, quote=True)), 4)
        self.assertNotIn(PAYLOAD, html)
        self.assert_safe_document(doc)
        chat_forms = doc.find('form', action='/chat')
        self.assertEqual(len(chat_forms), 1)
        self.assertEqual(chat_forms[0].find('input', name='csrf')[0].attrs['value'], self.csrf)
        self.assertEqual(len(doc.find('form', action='/chat/clear')), 1)
        _, unavailable = self.render('chat', chat_ready=False)
        self.assertFalse(unavailable.find('form', action='/chat'))
        self.assertFalse([n for n in unavailable.find('article') if 'chat-bubble' in n.classes()])

    def test_preview_parameters_cannot_inject_markup_paths_or_executable_attributes(self):
        for page in ('home', 'shop'):
            with self.subTest(page=page):
                html, doc = self.render(page, query={'preview': PAYLOAD, 'slot': PAYLOAD,
                                                     'mode': PAYLOAD, 'pose': PAYLOAD})
                self.assertNotIn(PAYLOAD, html)
                self.assert_safe_document(doc)
                self.assertFalse(doc.find('img', src='x'))
                stage = self.stage(doc, 'home-avatar' if page == 'home' else 'shop-avatar')
                self.assertEqual(stage.attrs['data-pose'], 'happy')
                self.assertEqual(stage.find('div', **{'class': 'pig-figure'})[0].attrs['data-garment'], '')
                for img in doc.find('img'):
                    self.assertTrue(img.attrs['src'].startswith('/static/assets/handdrawn/'))
                    self.assertTrue((ROOT / img.attrs['src'].lstrip('/')).is_file())

    def test_same_slot_purchases_render_only_the_current_fitted_layers(self):
        self.state['energy'] = 20000
        for item in ('coat', 'hoodie', 'glasses', 'rimless', 'bow', 'rosebow',
                     'sofa', 'ring', 'beach', 'lab', 'poodle', 'rabbit'):
            self.act('buy', id=item)
        self.act('buy', id='color-brown')
        self.act('use_color', color='brown')
        before = deepcopy(self.state)
        _, doc = self.render('home', query={'pose': 'wave'})
        self.assertEqual(self.state, before)
        stage = self.stage(doc, 'home-avatar')
        self.assertEqual(stage.attrs['data-seat'], 'ring')
        self.assertEqual(stage.attrs['data-skin'], 'brown')
        self.assertEqual(stage.attrs['data-companion'], 'rabbit')
        figure = stage.find('div', **{'class': 'pig-figure'})[0]
        self.assertEqual(figure.attrs['data-garment'], 'hoodie')
        sources = [n.attrs['src'].rsplit('/', 1)[-1] for n in stage.find('img')]
        for filename in ('hoodie.png', 'hoodie-wave-v31.png', 'glasses-rimless.svg', 'bow-rose.svg'):
            self.assertIn(filename, sources)
        for filename in ('coat.png', 'coat-wave-v31.png', 'glasses.svg', 'bow.svg'):
            self.assertNotIn(filename, sources)
        self.assertEqual(len([n for n in stage.find('img') if 'fitted-fabric' in n.classes()]), 2)
        room = next(n for n in doc.find('section') if 'room' in n.classes())
        self.assertEqual(room.attrs['data-scene'], 'lab')
        self.act('equip', id='hoodie')
        _, removed = self.render('home')
        self.assertEqual(self.stage(removed, 'home-avatar').find('div', **{'class': 'pig-figure'})[0].attrs['data-garment'], '')
        self.assertIn('hoodie', self.state['owned'], 'Taking off an item must keep ownership')

    def test_every_shop_preview_is_free_temporary_and_keeps_other_slots(self):
        self.state['energy'] = 20000
        for item in ('coat', 'glasses', 'bow', 'sofa', 'beach', 'poodle'):
            self.act('buy', id=item)
        before = deepcopy(self.state)
        for item in CATALOG['items']:
            with self.subTest(item=item['id']):
                _, doc = self.render('shop', query={'preview': item['id'], 'slot': item['slot']})
                self.assertEqual(self.state, before, 'A GET preview must not change any business state')
                expected = dict(before['equipped'])
                skin = item['color'] if item['slot'] == 'color' else before['skin']
                if item['slot'] != 'color':
                    expected[item['slot']] = item['id']
                stage = self.stage(doc)
                self.assertEqual(stage.attrs['data-skin'], skin)
                self.assertEqual(stage.attrs['data-seat'], expected['seat'])
                self.assertEqual(stage.attrs['data-companion'], expected['pet'])
                figure = stage.find('div', **{'class': 'pig-figure'})[0]
                self.assertEqual(figure.attrs['data-garment'], expected['clothes'])
                room = next(n for n in doc.find('section') if 'room' in n.classes())
                self.assertEqual(room.attrs['data-scene'], expected['background'])
                self.assert_safe_document(doc)
                for image in doc.find('img'):
                    self.assertTrue((ROOT / image.attrs['src'].lstrip('/')).is_file(), image.attrs['src'])

    def test_css_assets_and_fitted_garment_masks_exist(self):
        files = [ROOT / 'static' / filename for filename in ('style.css', 'avatar.css')]
        references = []
        for path in files:
            css = path.read_text(encoding='utf-8')
            for value in re.findall(r'url\(\s*([^)]+?)\s*\)', css):
                value = value.strip('\'"')
                references.append(value)
                self.assertFalse(urlsplit(value).scheme, 'Artwork must load locally')
                resolved = (path.parent / value).resolve()
                self.assertTrue(resolved.is_relative_to(ROOT / 'static'), value)
                self.assertTrue(resolved.is_file(), f'{path.name}: missing {value}')
        self.assertTrue(references)
        css = files[1].read_text(encoding='utf-8')
        for item in CATALOG['items']:
            if item['slot'] == 'clothes':
                for suffix in ('-mask.svg', '-wave-mask.svg'):
                    self.assertIn('assets/handdrawn/' + item['id'] + suffix, css)


if __name__ == '__main__':
    unittest.main()
