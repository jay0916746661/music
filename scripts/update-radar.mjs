import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { xml2js } = require("xml-js");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const sourcesPath = path.join(rootDir, "data", "radar-sources.json");
const outputPath = path.join(rootDir, "data", "lick-radar.json");

function firstText(node, name) {
  const entry = node?.elements?.find((item) => item.name === name);
  const textNode = entry?.elements?.find((item) => item.type === "text" || item.type === "cdata");
  return textNode?.text?.trim() || "";
}

function collectEntries(feedJson) {
  const feed = feedJson?.elements?.find((item) => item.name === "feed");
  if (feed) {
    return feed.elements?.filter((item) => item.name === "entry") || [];
  }
  const rss = feedJson?.elements?.find((item) => item.name === "rss");
  const channel = rss?.elements?.find((item) => item.name === "channel");
  return channel?.elements?.filter((item) => item.name === "item") || [];
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: {
      "user-agent": "SonicAtlasRadar/1.0"
    }
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return response.text();
}

async function resolveYoutubeFeedUrl(source) {
  const html = await fetchText(source.url);
  const channelId =
    html.match(/"channelId":"(UC[^"]+)"/)?.[1] ||
    html.match(/"externalId":"(UC[^"]+)"/)?.[1] ||
    html.match(/channel_id=(UC[\w-]+)/)?.[1];

  if (!channelId) {
    throw new Error(`Could not resolve YouTube channel id for ${source.label}`);
  }
  return `https://www.youtube.com/feeds/videos.xml?channel_id=${channelId}`;
}

function normalizeTitle(title) {
  return title
    .replace(/\[[^\]]+\]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function deriveTags(source, title) {
  const lower = `${title} ${source.tags.join(" ")}`.toLowerCase();
  const tags = new Set(source.tags);
  if (lower.includes("lick")) tags.add("lick");
  if (lower.includes("lesson")) tags.add("lesson");
  if (lower.includes("chord")) tags.add("chords");
  if (lower.includes("solo")) tags.add("solo");
  if (lower.includes("muse")) tags.add("notation");
  return [...tags].slice(0, 4);
}

function makeNote(source, title) {
  if (source.lane === "Logic") {
    return `從「${title}」切出一個可直接轉成段落推進的觀察，優先聽 automation、空間和 hook 排法。`;
  }
  if (source.lane === "MuseScore") {
    return `把「${title}」裡最值得留下來的節奏或和聲記成譜，順手輸出成 MusicXML 或 MIDI 草稿。`;
  }
  return `把「${title}」當成今天的樂句候選，先抓節奏語氣，再決定要不要進你的主練清單。`;
}

async function fetchSourceItems(source) {
  if (source.type === "instagram_placeholder") {
    return [];
  }

  const feedUrl = source.type === "youtube_handle" ? await resolveYoutubeFeedUrl(source) : source.url;
  const xml = await fetchText(feedUrl);
  const feedJson = xml2js(xml, { compact: false });
  const entries = collectEntries(feedJson).slice(0, 4);

  return entries.map((entry, index) => {
    const title = normalizeTitle(firstText(entry, "title"));
    const url =
      entry.elements?.find((item) => item.name === "link")?.attributes?.href ||
      firstText(entry, "link");

    return {
      id: `${source.id}-${index}`,
      title,
      lane: source.lane,
      source: `${source.label} / ${source.type}`,
      note: makeNote(source, title),
      tags: deriveTags(source, title),
      url
    };
  }).filter((item) => item.title);
}

async function main() {
  const raw = await fs.readFile(sourcesPath, "utf8");
  const sources = JSON.parse(raw);
  const results = [];
  const failures = [];

  for (const source of sources) {
    try {
      const items = await fetchSourceItems(source);
      results.push(...items);
    } catch (error) {
      failures.push({
        source: source.label,
        reason: error.message
      });
    }
  }

  const output = {
    updatedAt: new Date().toISOString(),
    items: results.slice(0, 12),
    meta: {
      supportedSources: ["youtube_handle", "rss"],
      unsupportedSources: ["instagram_placeholder"],
      failures
    }
  };

  await fs.writeFile(outputPath, `${JSON.stringify(output, null, 2)}\n`);
  console.log(`Updated radar with ${output.items.length} items`);
  if (failures.length) {
    console.log(`Skipped ${failures.length} sources`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
