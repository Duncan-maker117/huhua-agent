(function (global) {
  'use strict';

  const allowedTags = [
    'a', 'p', 'br', 'strong', 'em', 'del', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'hr',
    'table', 'thead', 'tbody', 'tr', 'th', 'td'
  ];
  const allowedProtocols = new Set(['http:', 'https:', 'mailto:', 'tel:']);
  let completeParser;
  let streamingParser;

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[character]));
  }

  function isFormattingContext(lexer, tokens) {
    if (lexer.state.inRawBlock) return false;
    // Leave intraword ASCII literals (for example x**2) to standard Marked.
    const previous = tokens.length ? tokens[tokens.length - 1].raw || '' : '';
    return !/[A-Za-z0-9_]$/.test(previous);
  }

  function looseStrong() {
    return {
      name: 'chatLooseStrong',
      level: 'inline',
      start(source) { return source.indexOf('**'); },
      tokenizer(source, tokens) {
        if (!isFormattingContext(this.lexer, tokens)) return;
        // A narrow presentation tolerance for **title **. The Markdown lexer
        // still owns code, escaped delimiters, links, lists and all other rules.
        const match = /^\*\*([^\s*][^\n*]*?)[ \t]+\*\*(?!\*)/.exec(source);
        if (!match) return;
        return {
          type: 'chatLooseStrong', raw: match[0],
          tokens: this.lexer.inlineTokens(match[1])
        };
      },
      renderer(token) {
        return `<strong>${this.parser.parseInline(token.tokens)}</strong>`;
      }
    };
  }

  function pendingStrong() {
    return {
      name: 'chatPendingStrong',
      level: 'inline',
      start(source) { return source.indexOf('**'); },
      tokenizer(source, tokens) {
        if (!isFormattingContext(this.lexer, tokens)) return;
        if (!source.startsWith('**') || source.startsWith('***')) return;
        // A complete pair belongs to the normal parser or looseStrong.
        if (source.slice(2).includes('**')) return;
        if (source === '**' || source.startsWith('**\n')) {
          return { type: 'chatPendingStrong', raw: '**', tokens: [] };
        }
        const match = /^\*\*([^\s*][^\n*]*?)(?:\*)?(?=\n|$)/.exec(source);
        if (!match) return;
        return {
          type: 'chatPendingStrong', raw: match[0],
          tokens: this.lexer.inlineTokens(match[1])
        };
      },
      renderer(token) {
        const body = this.parser.parseInline(token.tokens);
        return body ? `<strong>${body}</strong>` : '';
      }
    };
  }

  function makeParser(streaming) {
    const extensions = [looseStrong()];
    if (streaming) extensions.push(pendingStrong());
    return new global.marked.Marked({
      gfm: true,
      breaks: true,
      async: false,
      extensions,
      renderer: {
        // No remote resource is created, even before sanitization. Raw HTML is
        // displayed as text; Markdown image syntax keeps only its alt text.
        html(token) { return escapeHtml(token.text); },
        image(token) { return escapeHtml(token.text || ''); }
      }
    });
  }

  function prepareLinks(fragment) {
    fragment.querySelectorAll('a').forEach(link => {
      const href = link.getAttribute('href');
      if (!href) return;
      try {
        const url = new global.URL(href, global.location.href);
        if (!allowedProtocols.has(url.protocol)) {
          link.removeAttribute('href');
          return;
        }
        // Deterministic attributes added to already sanitized nodes. No raw
        // source is reparsed and no arbitrary attribute is copied here.
        link.setAttribute('target', '_blank');
        link.setAttribute('rel', 'noopener noreferrer');
      } catch (_) {
        link.removeAttribute('href');
      }
    });
  }

  function render(element, rawText, options) {
    if (!element || element.nodeType !== 1) return { mode: 'unavailable' };
    const source = typeof rawText === 'string' ? rawText : String(rawText ?? '');
    const streaming = Boolean(options && options.streaming);
    element.classList.add('chat-markdown');
    try {
      if (!global.marked || !global.DOMPurify || !global.DOMPurify.isSupported) {
        throw new Error('Markdown dependencies unavailable');
      }
      if (!completeParser) completeParser = makeParser(false);
      if (!streamingParser) streamingParser = makeParser(true);
      const html = (streaming ? streamingParser : completeParser).parse(source);
      const fragment = global.DOMPurify.sanitize(html, {
        ALLOWED_TAGS: allowedTags,
        ALLOWED_ATTR: ['href', 'title', 'start'],
        ALLOW_DATA_ATTR: false,
        ALLOW_ARIA_ATTR: false,
        FORBID_TAGS: ['img', 'script', 'style', 'svg', 'math', 'iframe', 'object', 'embed', 'form', 'input'],
        FORBID_ATTR: ['style', 'src', 'srcset'],
        RETURN_DOM_FRAGMENT: true
      });
      prepareLinks(fragment);
      element.replaceChildren(fragment);
      element.classList.remove('chat-markdown-fallback');
      return { mode: 'markdown', streaming };
    } catch (_) {
      // A dependency or parse failure must not become unsafe innerHTML.
      element.textContent = source;
      element.classList.add('chat-markdown-fallback');
      return { mode: 'plain', streaming };
    }
  }

  global.HuhuaMarkdown = Object.freeze({ render });
})(window);
