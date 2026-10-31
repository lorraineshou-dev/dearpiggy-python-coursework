"""Server-rendered pages. All durable state and business rules live in game.py.

The only browser script enhances audio, a breathing guide, photo resizing and
an ephemeral worry animation. Every game change is an ordinary HTML form.
"""
from datetime import date, timedelta
from html import escape
from urllib.parse import urlencode

from game import CATALOG, recommendations

ASSETS = '/static/assets/handdrawn/'
ITEMS = {item['id']: item for item in CATALOG['items']}
POSES = {'happy': ('开心', 'Happy'), 'listen': ('听你说', 'Listening'),
         'sleep': ('打个盹', 'Sleepy'), 'wave': ('打招呼', 'Hello')}
NAV = [('home', '/', '⌂', '小屋', 'Home'), ('care', '/care', '♡', '照顾', 'Care'),
       ('feelings', '/feelings', '☁', '心情', 'Feelings'), ('chat', '/chat', '♧', '聊天', 'Chat'),
       ('shop', '/shop', '✧', '衣橱', 'Wardrobe'), ('growth', '/growth', '♧', '成长', 'Growth'),
       ('settings', '/settings', '⚙', '设置', 'Settings')]


def e(value):
    return escape(str(value), quote=True)


def image(filename, css, lazy=False, extra=''):
    return (f'<img src="{ASSETS}{e(filename)}" class="{e(css)}" alt="" '
            f'{"loading=lazy" if lazy else ""} decoding="async" {extra}>')


def avatar(state, wear=None, skin=None, pose='happy', identifier='', scene=False, lazy=False):
    """Render registered artwork layers, including fitted garments and poses."""
    wear = dict(state['equipped'] if wear is None else wear)
    wear = {slot: key for slot, key in wear.items() if key in ITEMS and ITEMS[key]['slot'] == slot}
    skin = skin if skin in CATALOG['skins'] else state['skin']
    pose = pose if pose in POSES else 'happy'
    seat = wear.get('seat', 'blanket')
    garment = wear.get('clothes', '')
    pig = 'pig.png'
    painted = garment + '.png' if garment else pig
    wave = (garment or 'pig') + '-wave-v31.png'
    body = image(pig, 'reference-pig-image', lazy)
    if garment:
        body += image(painted, 'fitted-pig', lazy)
    if skin == 'tricolor':
        body += image(painted, 'reference-pig-patches', lazy)
        body += image(painted, 'reference-pig-patches reference-pig-patches-brown', lazy)
    if garment and skin != 'pink':
        body += image(painted, 'fitted-fabric', lazy)
    head = image(pig, 'reference-pig-image', lazy)
    head += image('pig-sleep-v31.png', 'reference-pig-image sleeping-expression', lazy)
    if skin in ('black', 'brown', 'tricolor'):
        cls = 'reference-pig-patches' if skin == 'tricolor' else 'reference-face-details'
        head += image(pig, cls, lazy) + image('pig-sleep-v31.png', cls + ' sleeping-expression', lazy)
    accessories = {'glasses': 'glasses.svg', 'rimless': 'glasses-rimless.svg',
                   'silver-round': 'silver-round.svg', 'bow': 'bow.svg', 'rosebow': 'bow-rose.svg',
                   'sunglasses-square': 'sunglasses-square.svg', 'sunglasses-round': 'sunglasses-round.svg',
                   'earbuds': 'earbuds-v31.svg', 'headphones': 'headphones-fitted-v31.svg'}
    for key in wear.values():
        if key in accessories:
            head += image(accessories[key], 'accessory', lazy)
    if 'strawhat' in wear.values():
        head += '<div class="head-accessory strawhat"></div>'
    waving = image(wave, 'reference-pig-image', lazy)
    if skin == 'tricolor':
        waving += image(wave, 'reference-pig-patches', lazy)
        waving += image(wave, 'reference-pig-patches reference-pig-patches-brown', lazy)
    if garment and skin != 'pink':
        waving += image(wave, 'fitted-fabric', lazy)
    companion = wear.get('pet', '')
    return (f'<div class="avatar reference-avatar {"with-scene" if scene else ""}" '
            f'{f"id={e(identifier)}" if identifier else ""} '
            f'data-seat="{e(seat)}" data-skin="{e(skin)}" data-pose="{pose}" '
            f'data-scene="{e(wear.get("background", "room") if scene else "room")}" '
            f'data-companion="{e(companion)}" aria-hidden="true">'
            '<div class="mount-sprite"></div><div class="pig-contact-shadow"></div>'
            f'<div class="pig-figure" data-garment="{e(garment)}"><div class="pig-body">{body}</div>'
            f'<div class="pig-wave-body">{waving}</div><div class="pig-head">{head}</div></div>'
            f'<div class="mount-sprite mount-front" data-seat="{e(seat)}"></div>'
            + (f'<div class="companion" data-pet="{e(companion)}"></div>' if companion else '') + '</div>')


class Page:
    def __init__(self, page, state, csrf, query):
        self.page, self.s, self.csrf, self.q = page, state, csrf, query or {}
        self.en = state['lang'] == 'en'
        self.path = '/' if page in ('home', 'welcome') else '/' + page

    def t(self, zh, en):
        return en if self.en else zh

    def tr(self, pair):
        return e(pair[1 if self.en else 0])

    def hidden(self, name, value):
        return f'<input type="hidden" name="{e(name)}" value="{e(value)}">'

    def form(self, action, contents, fields=None, css='', next_path=None, extra=''):
        hidden = self.hidden('csrf', self.csrf) + self.hidden('action', action)
        hidden += self.hidden('next', next_path or self.path)
        hidden += ''.join(self.hidden(k, v) for k, v in (fields or {}).items())
        return f'<form action="/action" method="post" class="{e(css)}" {extra}>{hidden}{contents}</form>'

    def button(self, text, css='primary', disabled=False, label=''):
        return (f'<button class="{e(css)}" type="submit" {"disabled" if disabled else ""} '
                f'{"aria-label=" + chr(34) + e(label) + chr(34) if label else ""}>{e(text)}</button>')

    def title(self, eyebrow, title, desc):
        return f'<header class="page-title"><span class="eyebrow">{e(eyebrow)}</span><h1>{e(title)}</h1><p>{e(desc)}</p></header>'

    def categories(self):
        result = {k: v for k, v in CATALOG['categories'].items() if k != 'all'}
        result.update({c['id']: [c['zh'], c['en']] for c in self.s['categories']})
        return result

    def category_select(self, selected='body'):
        return '<select name="category" aria-label="' + self.t('分类', 'Category') + '">' + ''.join(
            f'<option value="{e(key)}" {"selected" if key == selected else ""}>{self.tr(name)}</option>'
            for key, name in self.categories().items()) + '</select>'

    def mood_options(self, selected='', required=True):
        return '<div class="mood-options">' + ''.join(
            f'<label><input type="radio" name="mood" value="{e(m["id"])}" '
            f'{"checked" if selected == m["id"] else ""} {"required" if required else ""}>'
            f'<span><b class="face">{e(m["face"])}</b>{self.tr(m["name"])}</span></label>'
            for m in CATALOG['moods']) + '</div>'

    def habit(self, h, editable=False):
        done = h['id'] in self.s['done']
        name = h.get('en' if self.en else 'zh', h.get('title', ''))
        sub = self.tr(h['sub']) if h.get('sub') else self.tr(self.categories().get(h['category'], ['', '']))
        button = self.form('complete', self.button('✓' if done else '+', 'habit-complete', done,
                          self.t('完成：', 'Complete: ') + name), {'id': h['id']})
        content = (f'<article class="habit-card {"done" if done else ""}"><span class="habit-icon">{e(h["icon"])}</span>'
                   f'<div class="habit-text"><b>{e(name)}</b><small>{sub}</small></div>{button}</article>')
        if editable:
            edit = (f'<label>{self.t("小事名称", "Act name")}<input name="title" value="{e(name)}" maxlength="60" required></label>'
                    + self.category_select(h['category']) + self.button(self.t('保存修改', 'Save changes'), 'secondary'))
            content += '<details class="habit-edit"><summary>' + self.t('管理这件小事', 'Manage this act') + '</summary><div class="details-body">'
            if h['id'] not in {row['id'] for row in CATALOG['habits']}:
                content += self.form('edit_habit', edit, {'id': h['id']}, 'stack')
            content += self.form('delete_habit', self.button(self.t('从日常移除', 'Remove from routine'), 'text-button'), {'id': h['id']})
            content += '</div></details>'
        return content

    def language(self):
        return '<div class="language-controls" aria-label="Language">' + ''.join(
            self.form('language', self.button(label, 'language active' if self.s['lang'] == code else 'language'), {'lang': code})
            for code, label in [('zh-CN', '中文'), ('en', 'EN')]) + '</div>'

    def welcome(self):
        return (f'<div class="welcome-page">{self.language()}<span class="welcome-tag">A LITTLE KINDNESS, EVERY DAY</span>'
                '<div class="welcome-art"><span class="spark one">✧</span><span class="spark two">✦</span>'
                + image('pig.png', 'welcome-pig') + '<span class="welcome-heart">♡</span></div>'
                '<div class="welcome-copy"><h1>Dear Piggy</h1><p class="welcome-subtitle">'
                + self.t('亲爱的小猪，亲爱的自己。', 'A little pig. A softer place to land.') + '</p><p>'
                + self.t('不必每天都很厉害。<br>从一件小事开始，好好照顾自己。',
                         'You don’t have to do it all today.<br>Begin with one small act of care.') + '</p></div>'
                + self.form('welcome', self.button(self.t('以访客身份，进入小屋  →', 'Enter your little home  →'), 'primary welcome-enter'))
                + '<p class="fine-print">' + self.t('无需注册 · 此浏览器的进度保存在本机', 'No sign-up · Your browser profile is saved on this computer') + '</p>'
                + '<button type="button" class="text-button music-button" data-audio-toggle aria-pressed="false">♫ '
                + self.t('轻轻打开音乐', 'A little background music') + '</button></div>')

    def stage(self, wear=None, skin=None, preview=False):
        s, t = self.s, self.t
        wear = dict(s['equipped'] if wear is None else wear)
        pose = self.q.get('pose', 'sleep' if s['rest'] or not s['done'] else 'happy')
        if pose not in POSES:
            pose = 'happy'
        speech = t('今天什么都不做，也可以。', 'It’s okay to do nothing today.') if s['rest'] else t('你来了就很好，我们慢慢来。', 'It’s good to have you here. Let’s go slowly.')
        if preview:
            speech = t('免费试穿中 · 尚未保存', 'Free preview · not saved')
        return (f'<section class="room" data-scene="{e(wear.get("background", "room"))}">'
                f'<span class="room-chip">{t("☾ 一个安心的小角落", "☾ A soft place to land")}</span>'
                '<div class="window" aria-hidden="true"><i class="sun"></i><i class="hill"></i></div>'
                '<div class="wall-print" aria-hidden="true">♡<br>slow is okay</div><div class="floor"></div>'
                f'<p class="speech">{speech}</p><div class="stage-avatar">'
                + avatar(s, wear, skin, pose, 'shop-avatar' if self.page == 'shop' else 'home-avatar')
                + f'</div><div class="room-caption"><strong>{e(s["name"])}</strong><span>{t("一直在这里陪你", "Here with you")}</span></div></section>')

    def home(self):
        t, s = self.t, self.s
        greeting = t('今天，也对自己温柔一点', 'A little kindness for today')
        content = self.title(s['date'], greeting, t('不赶路，先听听自己的声音。', 'Take your time. Make a little room for yourself.')) + self.stage()
        content += '<nav class="pose-controls" aria-label="' + t('小猪动作', 'Piggy poses') + '">' + ''.join(
            f'<a href="/?pose={pose}" class="chip">{self.tr(name)}</a>' for pose, name in POSES.items()) + '</nav>'
        selected = s['checkin']
        check = '<h2>' + t('此刻的你，感觉怎么样？', 'How are you feeling right now?') + '</h2><fieldset><legend>' + t('选一个接近的心情', 'Choose a feeling that comes close') + '</legend>'
        check += self.mood_options(selected.get('mood', '')) + '</fieldset><fieldset><legend>' + t('今天还有多少力气？', 'How much energy do you have today?') + '</legend><div class="capacity-options">'
        for key, names in [('low', ('一点点', 'Just a little')), ('medium', ('还可以', 'Some energy')), ('high', ('挺充足', 'Feeling ready'))]:
            check += f'<label><input type="radio" name="capacity" value="{key}" {"checked" if selected.get("capacity") == key else ""} required><span>{self.tr(names)}</span></label>'
        check += '</div></fieldset>' + self.button(t('记住此刻的自己', 'Save my check-in'), 'secondary full')
        mood = next((m for m in CATALOG['moods'] if m['id'] == selected.get('mood')), None)
        if mood:
            check += '<p class="gentle-note">' + self.tr(mood['reply']) + '</p>'
        content += self.form('checkin', check, css='card checkin')
        content += '<section class="section"><div class="section-heading"><h2>' + t('今天的一点点照顾', 'A little care for today') + '</h2><a href="/care">' + t('全部小事 →', 'All little acts →') + '</a></div>'
        if s['rest']:
            content += '<p class="rest-card">' + t('今天可以安心休息。小猪会陪着你，成长不会倒退。', 'You can rest easy today. Piggy is here, and your growth stays with you.') + '</p>'
        else:
            picks = recommendations(s)
            content += ''.join(self.habit(h) for h in picks) if picks else '<p class="empty">' + t('今天已经照顾过自己了。给自己一个轻轻的拥抱。', 'You made room for yourself today. Give yourself a little kindness.') + '</p>'
        content += '</section><a class="breath-banner" href="/feelings#breathe"><i class="orb-mini"></i><span><b>' + t('和小猪一起，慢慢呼吸', 'A little breathing room') + '</b><small>' + t('留一分钟，轻轻松开肩膀', 'One minute. Let your shoulders soften.') + '</small></span><span>→</span></a>'
        content += '<p class="closing-note">' + t('你值得被照顾，不是因为你完成了多少。', 'You deserve care, however much you do today.') + '</p>'
        return content

    def care(self):
        t, s = self.t, self.s
        content = self.title('LITTLE ACTS, REAL CARE', t('把自己放在心上', 'Little acts of care'), t('从力所能及的小事开始。做一点，就很好。', 'Start with what feels possible. A little is enough.'))
        content += '<div class="soft-summary"><span>🌱</span><div><b>' + t(f'今天已照顾自己 {len(s["done"])} 次', f'{len(s["done"])} little acts today') + '</b><small>' + t('每天前 6 件小事各获得 10 能量，每一件都记入成长。', 'The first 6 acts earn 10 energy each; every act counts toward growth.') + '</small></div></div>'
        cats = {'all': ['全部', 'All'], **self.categories()}
        selected = self.q.get('category', 'all')
        content += '<nav class="filter-row" aria-label="' + t('小事分类', 'Habit categories') + '">' + ''.join(
            f'<a class="chip {"active" if key == selected else ""}" href="/care?{e(urlencode({"category": key}))}">{self.tr(name)}</a>' for key, name in cats.items()) + '</nav>'
        habits = [h for h in s['habits'] if selected == 'all' or h['category'] == selected]
        content += ''.join(self.habit(h, True) for h in habits) or '<p class="empty">' + t('这里还很安静。添一件自己的小事吧。', 'A quiet little space. Add something of your own.') + '</p>'
        contents = '<h2>' + t('添加自己的小事', 'Add an act of your own') + '</h2><label>' + t('什么小事会让你舒服一点？', 'What would feel kind to you?') + '<input name="title" maxlength="60" required placeholder="' + t('例如：走到窗边，看看云', 'For example: watch the clouds') + '"></label>'
        contents += self.category_select(selected if selected != 'all' else 'body') + self.button(t('添加到日常', 'Add to my routine'))
        content += self.form('add_habit', contents, css='card stack section')
        content += '<details class="card section"><summary>' + t('管理分类', 'Manage categories') + '</summary><div class="details-body">'
        content += self.form('add_category', '<label>' + t('新分类名称', 'New category name') + '<input name="title" maxlength="24" required></label>' + self.button(t('添加分类', 'Add category'), 'secondary'), css='stack')
        for c in s['categories']:
            content += '<div class="category-edit">' + self.form('edit_category', '<input name="title" value="' + e(c['en' if self.en else 'zh']) + '" maxlength="24" required aria-label="' + t('分类名称', 'Category name') + '">' + self.button(t('重命名', 'Rename'), 'secondary'), {'id': c['id']}, 'inline-form')
            content += self.form('delete_category', self.button(t('删除分类（小事移至身体照顾）', 'Delete category (move acts to Body)'), 'text-button'), {'id': c['id']}) + '</div>'
        content += '</div></details><section class="section"><h2>' + t('小事灵感库', 'A little inspiration') + '</h2>'
        existing = {h['id'] for h in s['habits']}
        removed = {h['id'] for h in s['removed_habits']}
        for h in CATALOG['habits']:
            action = 'restore_habit' if h['id'] in removed else 'add_habit'
            field = {'id': h['id']} if action == 'restore_habit' else {'catalog_id': h['id']}
            content += '<article class="library-item"><span>' + e(h['icon']) + '</span><div><b>' + e(h['en' if self.en else 'zh']) + '</b><small>' + self.tr(h['sub']) + '</small></div>'
            content += self.form(action, self.button(t('已添加', 'Added') if h['id'] in existing else t('添加', 'Add'), 'secondary', h['id'] in existing), field) + '</article>'
        content += '</section><details class="card section"><summary>' + t('已移除的小事', 'Removed little acts') + f' ({len(s["removed_habits"])})</summary><div class="details-body">'
        for h in s['removed_habits']:
            content += '<div class="library-item"><b>' + e(h['en' if self.en else 'zh']) + '</b>' + self.form('restore_habit', self.button(t('恢复', 'Restore'), 'secondary'), {'id': h['id']}) + '</div>'
        return content + '</div></details>'

    def feelings(self):
        t, s = self.t, self.s
        content = self.title('EVERY FEELING HAS A PLACE', t('心情，可以慢慢说', 'A place for every feeling'), t('开心与疲惫，都可以放在这里。', 'There is room for joy, tiredness, and everything between.'))
        fields = '<h2>' + t('记下这一刻', 'Keep a little moment') + '</h2><fieldset><legend>' + t('此刻的心情', 'Your feeling right now') + '</legend>' + self.mood_options(s['checkin'].get('mood', '')) + '</fieldset>'
        fields += '<label for="journal-note">' + t('今天，有什么想留下？', 'What would you like to remember?') + '</label><textarea id="journal-note" name="note" maxlength="500" rows="4" placeholder="' + t('一点点也可以。', 'A little is enough.') + '"></textarea>'
        fields += '<label class="photo-picker" for="photo-input">↗ ' + t('添加一张照片', 'Add a photo') + '<input type="file" id="photo-input" accept="image/jpeg,image/png,image/webp"></label>' + self.hidden('photo_data', '')
        fields += '<p id="photo-status" class="fine-print" role="status">' + t('JPG、PNG 或 WebP · 照片会在浏览器内缩小', 'JPG, PNG or WebP · Photos are resized in your browser') + '</p><div id="photo-draft" hidden><img id="photo-draft-image" alt="' + t('待保存的照片', 'Photo to save') + '"><button class="secondary" type="button" id="remove-photo">' + t('移除照片', 'Remove photo') + '</button></div>'
        fields += self.button(t('收好这一刻', 'Save this moment'), 'primary full')
        content += self.form('save_journal', fields, css='card journal-editor', extra='id="journal-form"')
        content += '<section id="breathe" class="card section breathing"><span class="eyebrow">A LITTLE PAUSE</span><h2>' + t('一起，慢慢呼吸', 'A gentle breathing pause') + '</h2><p>' + t('按自己的舒服节奏。随时可以停下。', 'Follow your own comfortable rhythm. Stop whenever you like.') + '</p><div class="breath-orb" id="breath-orb"><span id="breath-label">' + t('准备好了吗', 'Ready when you are') + '</span></div><p id="breath-time" aria-live="polite">' + t('一分钟的小小休息', 'A little one-minute pause') + '</p><div class="button-row"><button type="button" id="breath-start" class="primary">' + t('开始呼吸', 'Start breathing') + '</button><button type="button" id="breath-stop" class="secondary" hidden>' + t('暂停', 'Stop') + '</button></div><button type="button" class="text-button music-button" data-audio-toggle aria-pressed="false">♫ ' + t('轻缓音乐', 'Gentle music') + '</button>'
        if 'breathe' in {h['id'] for h in s['habits']} | {h['id'] for h in recommendations(s)}:
            content += self.form('complete', self.button(t('我给自己留了这一分钟', 'I took this minute for myself'), 'secondary', 'breathe' in s['done']), {'id': 'breathe'})
        content += '</section>'
        content += '<section class="card section worry"><span class="eyebrow">LET IT BE LIGHTER</span><h2>' + t('把烦恼，交给一朵云', 'Let a cloud carry a worry') + '</h2><p>' + t('写下后，轻轻放开。文字不会发送或保存。', 'Write it down, then let it go. These words are never sent or saved.') + '</p><label for="worry-input" class="sr-only">' + t('想放下的烦恼', 'A worry you want to release') + '</label><textarea id="worry-input" maxlength="1000" rows="3" autocomplete="off" placeholder="' + t('此刻压在心上的事……', 'Something weighing on your mind…') + '"></textarea><div id="worry-scene" class="worry-scene" aria-hidden="true"><div class="worry-cloud">☁</div><div class="worry-rainbow">🌈</div></div><p id="worry-status" role="status"></p><div class="button-row"><button type="button" id="worry-release" class="secondary">' + t('让它轻轻飘走', 'Let it drift away') + '</button><button type="button" id="worry-clear" class="text-button">' + t('清空文字', 'Clear words') + '</button></div></section>'
        content += '<section class="section"><h2>' + t('留给自己的小片段', 'Little moments you kept') + '</h2>'
        if not s['journal']:
            content += '<p class="empty">' + t('这里等着你的第一个小片段。', 'Your first little moment belongs here.') + '</p>'
        for entry in s['journal']:
            mood = next((m for m in CATALOG['moods'] if m['id'] == entry['mood']), None)
            content += '<article class="card entry"><header><b>' + (e(mood['face']) + ' ' + self.tr(mood['name']) if mood else '') + '</b><time>' + e(entry['date']) + '</time></header><p>' + e(entry['note']) + '</p>'
            photo = entry.get('photo', '')
            if photo and photo.startswith(('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')):
                content += f'<img class="entry-photo" src="{e(photo)}" alt="{t("心情小记照片", "Photo from this journal entry")}" loading="lazy">'
            content += self.form('delete_journal', self.button(t('删除这条小记', 'Delete this entry'), 'text-button'), {'id': entry['id']}) + '</article>'
        return content + '</section>'

    def chat(self, chat, ready, error):
        t = self.t
        content = self.title('A LITTLE COMPANY', t('小猪在听', 'Piggy is listening'), t('想说什么，都可以慢慢来。', 'Take your time. There is room for your words.'))
        content += '<div class="chat-stage">' + avatar(self.s, pose='listen', identifier='chat-avatar') + '</div>'
        content += '<p class="gentle-note">' + t('AI 陪聊可能会出错；它不是心理咨询或紧急支持。', 'AI chat can make mistakes. It is not counselling or emergency support.') + '</p>'
        if not ready:
            content += '<div class="card chat-unavailable"><h2>' + t('聊天服务还没有连接', 'Chat is not connected yet') + '</h2><p>' + t('可以继续照顾自己、记录心情，或让一朵云带走烦恼。配置好服务器的 AI 服务后，就可以在这里聊天。', 'You can still care for yourself, keep a journal, or let a cloud carry a worry. Chat becomes available when an AI service is configured on the server.') + '</p><a href="/feelings" class="secondary">' + t('去心情角落', 'Visit your feelings corner') + '</a></div>'
        content += '<div class="chat-history" aria-label="' + t('对话记录', 'Conversation') + '">'
        for item in chat or []:
            role = 'user' if item.get('role') == 'user' else 'assistant'
            content += f'<article class="chat-bubble {role}"><strong>{t("你", "You") if role == "user" else e(self.s["name"])}</strong><p>{e(item.get("content", ""))}</p></article>'
        content += '</div>'
        if error:
            content += '<p class="notice error" role="alert">' + e(error) + '</p>'
        if ready:
            content += '<form method="post" action="/chat" class="card stack chat-compose">' + self.hidden('csrf', self.csrf) + '<label for="chat-message">' + t('说给小猪听', 'Tell Piggy what is on your mind') + '</label><textarea id="chat-message" name="message" rows="3" maxlength="1000" required>' + e(self.q.get('draft', '')[:1000]) + '</textarea>' + self.button(t('发送', 'Send')) + '</form>'
        if chat:
            content += '<form method="post" action="/chat/clear">' + self.hidden('csrf', self.csrf) + self.button(t('清空这次对话', 'Clear this conversation'), 'text-button') + '</form>'
        return content + '<p class="fine-print">' + t('对话只保留在运行中的服务器内存里，不写入本地进度库。发送时会提交给配置的 AI 服务。', 'Chats stay in the running server’s memory and are not written to the local profile database. Sending a message submits it to the configured AI service.') + '</p>'

    def shop(self):
        t, s = self.t, self.s
        slot = self.q.get('slot', 'all')
        if slot not in CATALOG['slots']:
            slot = 'all'
        mode = self.q.get('mode', 'all')
        preview = ITEMS.get(self.q.get('preview', ''))
        wear, skin = dict(s['equipped']), s['skin']
        if preview:
            if preview['slot'] == 'color':
                skin = preview['color']
            else:
                wear[preview['slot']] = preview['id']
        content = self.title('LITTLE THINGS TO LOVE', t('给小猪，一点新意', 'A little change of clothes'), t('喜欢的样子，随时免费试试。', 'Try a look you love, whenever you like.'))
        content += self.stage(wear, skin, bool(preview))
        content += '<div class="outfit-caption"><span>' + self.tr(CATALOG['skins'][skin]) + ' · ' + e(' / '.join(ITEMS[key]['name'][1 if self.en else 0] for key in wear.values() if key in ITEMS)) + '</span>'
        if preview:
            content += '<a class="text-button" href="/shop">' + t('取消预览', 'Reset preview') + '</a>'
        content += '</div><nav class="shop-tabs" aria-label="' + t('物品范围', 'Collection') + '">'
        for key, label in [('all', t('全部好物', 'All treasures')), ('owned', t('我的衣橱', 'My wardrobe'))]:
            content += f'<a class="{"active" if mode == key else ""}" href="/shop?{e(urlencode({"mode": key, "slot": slot}))}">{label}</a>'
        content += '</nav><p class="fine-print">' + t('预览不消耗能量。兑换后永久拥有，同一部位自动替换。', 'Previewing is free. Unlocked items are yours to keep; each slot holds one item.') + '</p><nav class="filter-row" aria-label="' + t('衣橱分类', 'Wardrobe categories') + '">'
        for key, names in CATALOG['slots'].items():
            content += f'<a class="chip {"active" if key == slot else ""}" href="/shop?{e(urlencode({"slot": key, "mode": mode}))}">{self.tr(names)}</a>'
        content += '</nav>'
        if slot in ('all', 'color'):
            content += self.form('use_color', self.button(t('恢复默认粉色 · 免费', 'Restore default pink · free'), 'secondary', s['skin'] == 'pink'), {'color': 'pink'}, 'color-reset')
        content += '<section class="shop-grid" aria-label="' + t('物品目录', 'Item catalogue') + '">'
        count = 0
        for item in CATALOG['items']:
            dye = item['slot'] == 'color'
            owned = item.get('builtin') or item['id'] in s['owned']
            cards = s['cards'].get(item.get('color', ''), 0)
            if (slot != 'all' and item['slot'] != slot) or (mode == 'owned' and not (cards if dye else owned)):
                continue
            count += 1
            worn = s['equipped'].get(item['slot']) == item['id']
            gallery_wear = dict(s['equipped']) if dye else {item['slot']: item['id']}
            content += '<article class="shop-card"><div class="item-art">' + avatar(s, gallery_wear, item.get('color', s['skin']), 'happy', scene=item['slot'] == 'background', lazy=True)
            if dye or owned:
                content += '<span class="ownership">' + (t(f'持有 {cards} 张', f'{cards} cards') if dye else t('正在使用', 'In use') if worn else t('已拥有', 'Owned')) + '</span>'
            content += '</div><div class="item-info"><h3>' + self.tr(item['name']) + '</h3><span class="price">' + (t('默认拥有', 'Included') if item.get('builtin') else f'✦ {item["price"]}') + '</span><p>' + self.tr(item['desc']) + '</p><div class="item-buttons">'
            preview_link = '/shop?' + urlencode({'preview': item['id'], 'slot': slot, 'mode': mode})
            content += f'<a class="secondary" href="{e(preview_link)}" aria-label="{t("预览：", "Preview: ")}{self.tr(item["name"])}">{t("预览", "Try on")}</a>'
            if owned and not dye:
                label = t('使用中', 'In use') if item.get('builtin') and worn else t('收起', 'Put away') if worn else t('使用', 'Use')
                content += self.form('equip', self.button(label, 'primary', bool(item.get('builtin') and worn)), {'id': item['id']})
            else:
                label = t('兑换卡片', 'Get card') if dye else t('兑换并使用', 'Unlock')
                content += self.form('buy', self.button(label, 'primary', s['energy'] < item['price']), {'id': item['id']})
                if s['energy'] < item['price']:
                    content += '<small class="energy-short">' + t(f'还差 {item["price"] - s["energy"]} 能量', f'{item["price"] - s["energy"]} more energy') + '</small>'
            if dye and cards:
                content += self.form('use_color', self.button(t('使用 1 张', 'Use 1 card'), 'secondary', s['skin'] == item['color']), {'color': item['color']}, 'use-card')
            content += '</div></div></article>'
        if not count:
            content += '<p class="empty">' + t('这里还没有珍藏。先免费试试喜欢的样子吧。', 'No treasures here yet. Try a favorite look for free.') + '</p>'
        return content + '</section><aside class="card section shop-rules"><h2>' + t('慢慢积攒，也很可爱', 'Good things take their time') + '</h2><p>' + t('每天前 6 件小事各获得 10 暖心能量。衣物、背景和伙伴永久保留；改色卡每次使用消耗 1 张。这里不需要真实付款。', 'The first 6 daily acts earn 10 care energy each. Clothes, scenes and companions stay yours. Color cards are single-use. No real-money payments here.') + '</p></aside>'

    def growth(self):
        t, s = self.t, self.s
        total = s['total']
        content = self.title('GROW AT YOUR OWN PACE', t('每一点照顾，都算数', 'Every little act counts'), t('不需要连胜，也没有掉队。', 'No streak to protect. No falling behind.'))
        content += '<section class="card growth-card"><div class="leaf-art">🌱</div><h2>' + t('每一份照顾，都在悄悄发芽', 'Little acts quietly help us grow') + '</h2><p>' + t(f'再完成 {3 - total % 3} 件小事，长出下一片新叶。', f'{3 - total % 3} more little acts until your next leaf.') + f'</p><progress value="{total % 3}" max="3" aria-label="{t("下一片叶子的进度", "Progress toward your next leaf")}"></progress><div class="growth-metrics">'
        for number, names in [(total, ('照顾自己的次数', 'Acts of care')), (total // 3, ('小小新叶', 'Little leaves')), (len(s['owned']), ('温柔珍藏', 'Treasures'))]:
            content += f'<div><b>{number}</b><span>{self.tr(names)}</span></div>'
        content += '</div></section><section class="card section weekly"><h2>' + t('这一周的小心情', 'Little feelings this week') + '</h2><div class="week-moods">'
        today = date.fromisoformat(s['date'])
        for offset in range(6, -1, -1):
            day = today - timedelta(days=offset)
            entry = next((j for j in s['journal'] if j['date'][:10] == day.isoformat()), None)
            mood = next((m for m in CATALOG['moods'] if entry and m['id'] == entry['mood']), None)
            day_label = day.strftime('%a') if self.en else ['一', '二', '三', '四', '五', '六', '日'][day.weekday()]
            content += '<div class="day-dot"><span title="' + (self.tr(mood['name']) if mood else t('未记录', 'No entry')) + '">' + (e(mood['face']) if mood else '·') + f'</span><small>{day_label}</small></div>'
        content += '</div><p class="fine-print">' + t('空白的日子，也同样值得温柔。', 'The blank days deserve kindness, too.') + '</p></section>'
        rest = '<h2>' + t('今天，允许自己休息', 'Let today be a day for rest') + '</h2><label class="checkbox-row"><input type="checkbox" name="enabled" ' + ('checked' if s['rest'] else '') + '>' + t('开启今日休息模式', 'Rest mode for today') + '</label><p class="fine-print">' + t('暂停推荐，保留所有成长。明天自动重新开始。', 'Pause recommendations and keep all your growth. A fresh start tomorrow.') + '</p>' + self.button(t('保存', 'Save'), 'secondary')
        return content + self.form('rest', rest, css='card section preferences')

    def settings(self):
        t, s = self.t, self.s
        content = self.title('YOUR OWN LITTLE CORNER', t('把小屋，布置成自己的样子', 'Make this little home yours'), t('属于这个浏览器的本地小档案。', 'A local profile for this browser.'))
        content += '<section class="card settings-card"><h2>' + t('界面语言', 'Language') + '</h2>' + self.language() + '</section>'
        profile = '<h2>' + t('称呼与声音', 'Names and little sounds') + '</h2><label>' + t('小猪的名字', 'Piggy’s name') + f'<input name="name" value="{e(s["name"])}" maxlength="24" required></label><label>' + t('你的昵称（可选）', 'Your nickname (optional)') + f'<input name="nickname" value="{e(s["nickname"])}" maxlength="40"></label><label class="checkbox-row"><input type="checkbox" name="music" ' + ('checked' if s['music'] else '') + '>' + t('允许欢迎页背景音乐', 'Enable welcome music') + '</label>' + self.button(t('保存设置', 'Save settings'))
        content += self.form('profile', profile, css='card section stack')
        content += '<section class="card section privacy"><h2>' + t('你的进度，放在哪里？', 'Where does my progress live?') + '</h2><p>' + t('小猪、能量、衣橱和心情小记保存在本机 SQLite 数据库。浏览器用一个随机标识找到自己的档案，无需账户或密码。', 'Piggy, energy, your wardrobe and journal are stored in a SQLite database on this computer. A random browser identifier finds your profile, with no account or password.') + '</p><p>' + t('清除浏览器 Cookie 后，会创建新档案；旧档案仍保存在本机，但不会自动关联到新浏览器。关闭再打开程序，会保留原档案。', 'Clearing browser cookies creates a new profile. Your old profile stays on this computer but is not automatically linked to a new browser. Closing and reopening the app keeps your existing profile.') + '</p><p>' + t('烦恼文字不会发送或保存。AI 对话仅在服务运行期间保存在内存中，发送时会交给配置的 AI 提供方。', 'Worry text is never sent or stored. AI conversations stay in server memory while it runs; messages you send go to the configured AI provider.') + '</p></section>'
        return content


def render_page(page, state, csrf, query=None, chat=None, chat_ready=False, message='', chat_error=''):
    page = page if page in {'welcome', 'home', 'care', 'feelings', 'chat', 'shop', 'growth', 'settings'} else 'home'
    p = Page(page, state, csrf, query)
    t = p.t
    body = p.chat(chat, chat_ready, chat_error) if page == 'chat' else getattr(p, page)()
    title = 'Dear Piggy · ' + next((n[4 if p.en else 3] for n in NAV if n[0] == page), t('亲爱的小猪', 'A little kindness'))
    top = '' if page == 'welcome' else ('<header class="topbar"><a class="brand" href="/"><span>♡</span> Dear Piggy</a><div class="top-actions"><a class="energy-pill" href="/shop" aria-label="' + t('暖心能量', 'Care energy') + f'">✦ <b>{state["energy"]}</b></a><a class="settings-link" href="/settings" aria-label="{t("设置", "Settings")}">⚙</a></div></header>')
    nav = '' if page == 'welcome' else '<nav class="bottom-nav" aria-label="' + t('主要导航', 'Main navigation') + '">' + ''.join(
        f'<a href="{path}" {"aria-current=page" if page == key else ""}><span aria-hidden="true">{symbol}</span><b>{en if p.en else zh}</b></a>'
        for key, path, symbol, zh, en in NAV) + '</nav>'
    notice = f'<p class="notice" role="status">{e(message)}</p>' if message else ''
    return (f'<!doctype html><html lang="{e(state["lang"])}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="light"><meta name="theme-color" content="#f8f5f4">'
            f'<title>{e(title)}</title><link rel="stylesheet" href="/static/style.css"><link rel="stylesheet" href="/static/avatar.css">'
            '<script src="/static/enhance.js" defer></script></head>'
            f'<body data-page="{page}" data-music="{str(bool(state["music"])).lower()}"><a class="skip-link" href="#main">{t("跳到内容", "Skip to content")}</a>'
            '<aside class="desktop-note" aria-hidden="true"><span>DEAR PIGGY</span><h2>' + t('把日子过轻一点，<br>把自己放在心上。', 'A gentler day.<br>A little room<br>for yourself.') + '</h2><p>' + t('一只小猪，一点陪伴，一天一点点。', 'A little pig. A little company. One day at a time.') + '</p><div>☁</div></aside>'
            f'<div class="app-shell">{top}<main id="main">{notice}{body}</main>{nav}</div>'
            '<audio id="gentle-audio" src="/static/assets/welcome-music.m4a" preload="none" loop></audio>'
            '<noscript><p class="noscript-note">' + t('日常、心情小记和衣橱仍可使用。音乐、照片和云朵动画需要 JavaScript。', 'Care, journals and the wardrobe work without JavaScript. Music, photo resizing and the cloud animation need JavaScript.') + '</p></noscript></body></html>')
