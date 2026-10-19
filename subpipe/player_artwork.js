() => {
    const choices = [];
    function add(src, score) {
        if (!src) return;
        try {
            const url = new URL(src, document.baseURI);
            if (['http:', 'https:'].includes(url.protocol)) choices.push({url: url.href, score});
        } catch (_) {}
    }
    const selector = '.plyr,.video-js,.jwplayer,.mejs-container,.flowplayer,[data-player],.audio-player,.video-player,#player';
    const roots = new Set(document.querySelectorAll(selector));
    for (const media of document.querySelectorAll('video,audio')) {
        const root = media.closest(selector) || media.parentElement;
        if (root && root !== document.body) roots.add(root);
    }
    for (const root of roots) {
        for (const node of [root, ...root.querySelectorAll('img,[style],.plyr__poster,.vjs-poster,.jw-preview')]) {
            const rect = node.getBoundingClientRect();
            // Ignore icons and control artwork, but retain hidden startup covers.
            const large = Math.max(rect.width, node.naturalWidth || 0) >= 160 &&
                          Math.max(rect.height, node.naturalHeight || 0) >= 90;
            const cover = /poster|cover|preview|artwork/i.test(`${node.className} ${node.id}`);
            if (!large && !cover) continue;
            const score = cover ? 120 : 100;
            if (node.tagName === 'IMG') add(node.currentSrc || node.src || node.dataset.src, score);
            const background = getComputedStyle(node).backgroundImage;
            for (const match of background.matchAll(/url\(\s*(['"]?)(.*?)\1\s*\)/g)) add(match[2], score);
        }
    }
    for (const video of document.querySelectorAll('video[poster]')) add(video.poster, 90);
    for (const meta of document.querySelectorAll('meta[property="og:image"],meta[name="twitter:image"]')) add(meta.content, 50);
    choices.sort((a, b) => b.score - a.score);
    return {page_url: location.href, title: document.title,
            poster: choices[0]?.url || null, artwork_score: choices[0]?.score || 0};
}
