import "./explain.css";
import { marked } from "marked";

// The explainer is one Markdown file, docs/EXPLAINER.md, shown here as it is written.
const doc = document.querySelector<HTMLElement>("#doc")!;
const nav = document.querySelector<HTMLElement>("#doc-nav")!;

async function main(): Promise<void> {
  const res = await fetch("/api/explainer");
  if (!res.ok) throw new Error(`could not load the explainer (${res.status})`);
  doc.innerHTML = await marked.parse(await res.text());

  for (const heading of doc.querySelectorAll<HTMLElement>("h2")) {
    heading.id = heading.textContent!.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    const link = document.createElement("a");
    link.href = `#${heading.id}`;
    link.textContent = heading.textContent;
    nav.append(link);
  }
  // Wide tables and diagrams scroll inside their own box, never the page.
  for (const el of doc.querySelectorAll<HTMLElement>("table, pre")) {
    const box = document.createElement("div");
    box.className = "scroll";
    el.replaceWith(box);
    box.append(el);
  }
}

main().catch((error) => {
  doc.textContent = String(error);
});
