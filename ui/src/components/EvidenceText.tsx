import { createElement, useMemo, type ReactNode } from 'react';

// Rebuild retained table markup as React nodes; never insert source HTML.
const allowed = new Set([
  'table',
  'thead',
  'tbody',
  'tfoot',
  'tr',
  'th',
  'td',
  'caption',
  'colgroup',
  'col',
  'p',
  'br',
  'strong',
  'em',
  'ul',
  'ol',
  'li',
]);
function renderNode(node: Node, key: number): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent;
  if (!(node instanceof Element)) return null;
  const tag = node.tagName.toLowerCase();
  if (['script', 'style', 'iframe', 'object', 'svg', 'math'].includes(tag))
    return null;
  const children = Array.from(node.childNodes).map(renderNode);
  if (!allowed.has(tag)) return children;
  const props: Record<string, unknown> = { key };
  if (tag === 'td' || tag === 'th') {
    for (const [attribute, prop] of [
      ['colspan', 'colSpan'],
      ['rowspan', 'rowSpan'],
    ]) {
      const value = Number(node.getAttribute(attribute));
      if (Number.isInteger(value) && value > 0 && value <= 100)
        props[prop] = value;
    }
    if (
      tag === 'th' &&
      ['row', 'col', 'rowgroup', 'colgroup'].includes(
        node.getAttribute('scope') ?? '',
      )
    )
      props.scope = node.getAttribute('scope');
  }
  return createElement(
    tag,
    props,
    ...(['br', 'col'].includes(tag) ? [] : children),
  );
}

export default function EvidenceText({ text }: { text: string }) {
  const blocks = useMemo(
    () =>
      text.split(/(<table\b[^>]*>[\s\S]*?<\/table>)/gi).map((part, index) => {
        if (!/^<table\b/i.test(part))
          return (
            <div key={index} className="whitespace-pre-wrap break-words">
              {part}
            </div>
          );
        const document = new DOMParser().parseFromString(part, 'text/html');
        return (
          <div key={index} className="my-3 min-w-0">
            <p className="text-sm text-ink-3 mb-2">
              Source table · Scroll horizontally to read all columns.
            </p>
            <div
              className="evidence-table"
              tabIndex={0}
              role="region"
              aria-label="Source evidence table"
            >
              {Array.from(document.body.childNodes).map(renderNode)}
            </div>
          </div>
        );
      }),
    [text],
  );
  return <div className="min-w-0 text-sm leading-relaxed">{blocks}</div>;
}
