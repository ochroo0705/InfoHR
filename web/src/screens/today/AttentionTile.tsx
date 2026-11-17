import type { AttentionBoxOut } from "../../api/today";

// The «Хийх зүйл» tile (`_attention_tile.html`, id="attention-tile"). Its number is the box's urgent count, so it
// follows the box after a «Мэдлээ»: the parent passes the same `box` to both. The link scrolls to #attention.
export function AttentionTile({ box }: { box: AttentionBoxOut }) {
  return (
    <a id="attention-tile" href="#attention" className="card-soft flex items-center gap-3 p-4">
      <span className={`tile-icon ${box.urgent_count ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-500"}`}>
        <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
          <path
            fillRule="evenodd"
            d="M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm1-11a1 1 0 1 0-2 0v4a1 1 0 1 0 2 0V7Zm-1 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
            clipRule="evenodd"
          />
        </svg>
      </span>
      <span>
        <span className="block text-xs text-slate-500">Хийх зүйл</span>
        <span
          className={box.urgent_count ? "block text-2xl font-semibold leading-tight text-red-700" : "block text-2xl font-semibold leading-tight"}
          data-tile="attention"
        >
          {box.urgent_count}
        </span>
        <span className="block text-xs text-slate-500">
          + {box.soon_count} удахгүй · {box.gap_count} дутуу
        </span>
      </span>
    </a>
  );
}
