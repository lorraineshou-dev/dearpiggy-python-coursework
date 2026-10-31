/* Progressive media enhancements only. Python owns every game rule and save. */
'use strict';
(() => {
  const english = document.documentElement.lang === 'en';
  const words = (zh, en) => english ? en : zh;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const audio = document.getElementById('gentle-audio');
  const audioButtons = [...document.querySelectorAll('[data-audio-toggle]')];
  let audioBusy = false;
  const audioLabel = words('♫ 轻缓音乐', '♫ Gentle music');
  function reflectAudio() {
    audioButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(!audio.paused));
      button.textContent = audio.paused ? audioLabel : words('♫ 关闭音乐', '♫ Turn music off');
    });
  }
  audioButtons.forEach(button => button.addEventListener('click', async () => {
    if (audioBusy) return;
    if (!audio.paused) { audio.pause(); reflectAudio(); return; }
    audioBusy = true;
    try { audio.volume = 0.28; await audio.play(); reflectAudio(); }
    catch { button.textContent = words('暂时无法播放 · 可以安静地继续', 'Audio unavailable · a quiet moment is okay'); }
    finally { audioBusy = false; }
  }));
  if (document.body.dataset.page === 'welcome' && document.body.dataset.music === 'false') {
    audioButtons.forEach(button => button.hidden = true);
  }
  const start = document.getElementById('breath-start');
  const stop = document.getElementById('breath-stop');
  const orb = document.getElementById('breath-orb');
  const breathLabel = document.getElementById('breath-label');
  const breathTime = document.getElementById('breath-time');
  let breathTimer = null;
  function stopBreathing(finished = false) {
    clearInterval(breathTimer); breathTimer = null;
    if (!start) return;
    start.hidden = false; stop.hidden = true;
    orb.classList.remove('inhale', 'exhale');
    breathLabel.textContent = words('准备好了吗', 'Ready when you are');
    breathTime.textContent = finished ? words('谢谢你，给自己留了这一分钟。', 'Thank you for making this minute for yourself.') : words('一分钟的小小休息', 'A little one-minute pause');
  }
  start?.addEventListener('click', () => {
    if (breathTimer) return;
    const began = Date.now();
    start.hidden = true; stop.hidden = false;
    const tick = () => {
      const seconds = Math.floor((Date.now() - began) / 1000);
      if (seconds >= 60) { stopBreathing(true); return; }
      const inhale = seconds % 10 < 4;
      breathLabel.textContent = inhale ? words('慢慢吸气', 'Breathe in gently') : words('轻轻呼气', 'Breathe out softly');
      orb.classList.toggle('inhale', inhale); orb.classList.toggle('exhale', !inhale);
      breathTime.textContent = words(`还有 ${60 - seconds} 秒 · 随时可以停下`, `${60 - seconds} seconds left · Stop anytime`);
    };
    tick(); breathTimer = setInterval(tick, 1000);
  });
  stop?.addEventListener('click', () => stopBreathing());
  const worry = document.getElementById('worry-input');
  const release = document.getElementById('worry-release');
  const scene = document.getElementById('worry-scene');
  const worryStatus = document.getElementById('worry-status');
  let worryTimer = null;
  function clearWorry() {
    clearTimeout(worryTimer); worryTimer = null;
    if (!worry) return;
    worry.value = ''; release.disabled = false;
    scene.classList.remove('releasing', 'released'); worryStatus.textContent = '';
  }
  release?.addEventListener('click', () => {
    if (!worry.value.trim()) { worry.focus(); return; }
    // Worry text is cleared here and never copied, submitted, or persisted.
    worry.value = ''; release.disabled = true;
    scene.classList.remove('released'); scene.classList.add('releasing');
    worryStatus.textContent = words('交给云朵，轻轻放开。', 'Let the cloud carry it for a moment.');
    worryTimer = setTimeout(() => {
      scene.classList.remove('releasing'); scene.classList.add('released');
      worryStatus.textContent = words('不用马上解决一切。先让自己轻一点。', 'You don’t have to solve everything now. Make a little room to breathe.');
      release.disabled = false;
    }, reducedMotion.matches ? 10 : 3400);
  });
  document.getElementById('worry-clear')?.addEventListener('click', clearWorry);
  worry?.addEventListener('input', () => {
    if (!release.disabled) scene.classList.remove('released');
  });
  const photoInput = document.getElementById('photo-input');
  const journal = document.getElementById('journal-form');
  const photoData = journal?.querySelector('[name=photo_data]');
  const draft = document.getElementById('photo-draft');
  const draftImage = document.getElementById('photo-draft-image');
  const photoStatus = document.getElementById('photo-status');
  let photoBusy = false;
  function removePhoto() {
    if (!photoInput) return;
    photoInput.value = ''; photoData.value = ''; draft.hidden = true;
    draftImage.removeAttribute('src');
    photoStatus.textContent = words('JPG、PNG 或 WebP · 照片会在浏览器内缩小', 'JPG, PNG or WebP · Photos are resized in your browser');
  }
  document.getElementById('remove-photo')?.addEventListener('click', removePhoto);
  journal?.addEventListener('submit', event => { if (photoBusy) event.preventDefault(); });
  photoInput?.addEventListener('change', async () => {
    const file = photoInput.files?.[0];
    if (!file) return;
    const submit = journal.querySelector('button[type=submit]');
    let objectURL = null;
    photoBusy = true; submit.disabled = true;
    try {
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error(words('请选择 JPG、PNG 或 WebP 照片。', 'Please choose a JPG, PNG or WebP photo.'));
      if (file.size > 10 * 1024 * 1024) throw new Error(words('请选择小于 10 MB 的照片。', 'Please choose a photo smaller than 10 MB.'));
      photoStatus.textContent = words('正在缩小照片……', 'Resizing your photo…');
      objectURL = URL.createObjectURL(file);
      const photo = new Image(); photo.src = objectURL;
      await photo.decode();
      const scale = Math.min(1, 1400 / Math.max(photo.naturalWidth, photo.naturalHeight));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(photo.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(photo.naturalHeight * scale));
      const context = canvas.getContext('2d');
      context.fillStyle = '#fffdfb'; context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(photo, 0, 0, canvas.width, canvas.height);
      const data = canvas.toDataURL('image/jpeg', 0.82);
      if (data.length > 2.6 * 1024 * 1024) throw new Error(words('这张照片仍然太大，请换一张。', 'This photo is still too large. Please choose another.'));
      photoData.value = data; draftImage.src = data; draft.hidden = false;
      photoStatus.textContent = words('照片准备好了，会和这条小记一起保存。', 'Your photo is ready to save with this entry.');
    } catch (error) {
      removePhoto();
      photoStatus.textContent = error.message.startsWith('Please') || /请选择|这张照片仍然/.test(error.message) ? error.message : words('这张照片没能读取，请换一张试试。', 'This photo could not be read. Please try another.');
    } finally {
      if (objectURL) URL.revokeObjectURL(objectURL);
      photoBusy = false; submit.disabled = false; photoInput.value = '';
    }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { audio.pause(); reflectAudio(); stopBreathing(); }
  });
  window.addEventListener('pagehide', () => { audio.pause(); stopBreathing(); clearWorry(); });
})();
