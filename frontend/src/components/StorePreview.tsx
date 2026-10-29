import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import type { Snapshot } from "../types";

interface Props {
  snapshot: Snapshot | null;
  apiProducts: Record<string, unknown>[] | null;
  canFetch: boolean;
  canAddToCart: boolean;
  busy: boolean;
  onFetch: () => void;
  onAddToCart: (productId: number) => void;
  onSeed: () => void;
}

interface Card {
  id: number;
  name: string;
  price: string;
  stock: number | null;
  category: string | null;
  tags: string[];
}

const rowsOf = (snapshot: Snapshot | null, table: string) =>
  snapshot?.tables.find((t) => t.name === table)?.rows ?? [];

const money = (v: unknown) => {
  const n = Number(v);
  return Number.isFinite(n) ? `$${n.toFixed(2)}` : String(v ?? "");
};

export default function StorePreview({ snapshot, apiProducts, canFetch, canAddToCart, busy, onFetch, onAddToCart, onSeed }: Props) {
  const [category, setCategory] = useState<string | null>(null);

  const { cards, source, carts } = useMemo(() => {
    const dbProducts = rowsOf(snapshot, "store_product");
    const cats = new Map(rowsOf(snapshot, "store_category").map((r) => [r.id, String(r.name)]));
    const tags = new Map(rowsOf(snapshot, "store_tag").map((r) => [r.id, String(r.name)]));
    const links = rowsOf(snapshot, "store_product_tags");
    let cards: Card[] = [];
    let source: "db" | "api" | null = null;
    if (dbProducts.length) {
      source = "db";
      cards = dbProducts.map((p) => ({
        id: Number(p.id), name: String(p.name ?? `Product ${p.id}`), price: money(p.price),
        stock: p.stock === undefined ? null : Number(p.stock),
        category: p.category_id !== undefined ? cats.get(p.category_id) ?? `#${p.category_id}` : null,
        tags: links.filter((l) => l.product_id === p.id).map((l) => tags.get(l.tag_id) ?? "?"),
      }));
    } else if (apiProducts?.length) {
      source = "api";
      cards = apiProducts.map((p, i) => ({
        id: Number(p.id ?? i + 1), name: String(p.name ?? "Unnamed"), price: money(p.price),
        stock: typeof p.stock === "number" ? p.stock : null,
        category: typeof p.category === "string" ? p.category : null, tags: [],
      }));
    }
    const products = new Map(dbProducts.map((p) => [p.id, p]));
    const items = rowsOf(snapshot, "store_cartitem");
    const carts = rowsOf(snapshot, "store_cart").map((c) => {
      const lines = items.filter((it) => it.cart_id === c.id).map((it) => {
        const p = products.get(it.product_id);
        return { name: String(p?.name ?? `#${it.product_id}`), qty: Number(it.quantity ?? 1), price: Number(p?.price ?? 0) };
      });
      return { id: Number(c.id), lines, total: lines.reduce((s, l) => s + l.qty * l.price, 0) };
    });
    return { cards, source, carts };
  }, [snapshot, apiProducts]);

  const categories = [...new Set(cards.map((c) => c.category).filter((c): c is string => !!c))];
  const shown = category ? cards.filter((c) => c.category === category) : cards;

  return (
    <div className="store">
      <div className="store-nav">
        <div className="store-brand">◆ Forge Outfitters</div>
        <div className="store-actions">
          {canFetch && <button className="btn btn-ghost btn-sm" onClick={onFetch} disabled={busy}>GET /api/products/</button>}
          <button className="btn btn-ghost btn-sm" onClick={onSeed} disabled={busy}>Insert sample data</button>
        </div>
      </div>
      {source && (
        <div className="store-source">
          {source === "db"
            ? "Rendered from rows in your database: this is the data your models actually stored."
            : "Rendered from your API's JSON response (there's no Product table yet)."}
        </div>
      )}
      {categories.length > 1 && (
        <div className="cat-filter">
          <button className={`chip ${!category ? "chip-on" : ""}`} onClick={() => setCategory(null)}>All</button>
          {categories.map((c) => (
            <button key={c} className={`chip ${category === c ? "chip-on" : ""}`} onClick={() => setCategory(c)}>{c}</button>
          ))}
        </div>
      )}
      {!cards.length ? (
        <div className="empty">
          <div className="empty-icon">🛍</div>
          <h3>Your storefront is empty</h3>
          <p>
            Products appear here once your API returns them or your database stores them.
            {canFetch ? " Fetch GET /api/products/ to render its response." : " Start with Mission 1: build GET /api/products/."}
          </p>
        </div>
      ) : (
        <div className="product-grid">
          {shown.map((c, i) => (
            <motion.div key={`${source}-${c.id}`} className="product-card" initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
              <div className="product-img" style={{ background: `hsl(${(c.id * 67) % 360} 45% 22%)` }}>
                {c.name.slice(0, 1)}
              </div>
              <div className="product-body">
                {c.category && <div className="product-cat">{c.category}</div>}
                <div className="product-name">{c.name}</div>
                <div className="product-row">
                  <span className="product-price">{c.price}</span>
                  {c.stock !== null && (
                    <span className={`stock ${c.stock === 0 ? "out" : ""}`}>{c.stock === 0 ? "Out of stock" : `${c.stock} in stock`}</span>
                  )}
                </div>
                {c.tags.length > 0 && <div className="tags">{c.tags.map((t) => <span key={t}>#{t}</span>)}</div>}
                {canAddToCart && source === "db" && (
                  <button className="btn btn-accent btn-sm btn-block" disabled={busy} onClick={() => onAddToCart(c.id)}>
                    Add to cart
                  </button>
                )}
              </div>
            </motion.div>
          ))}
        </div>
      )}
      {carts.length > 0 && (
        <div className="carts">
          <h4>Carts in the database</h4>
          {carts.map((c) => (
            <div key={c.id} className="cart">
              <div className="cart-head"><b>Cart #{c.id}</b><span>{money(c.total)}</span></div>
              {c.lines.length ? c.lines.map((l, i) => (
                <div key={i} className="cart-line"><span>{l.qty} × {l.name}</span><span>{money(l.qty * l.price)}</span></div>
              )) : <div className="muted">empty</div>}
            </div>
          ))}
        </div>
      )}
      {canAddToCart && (
        <p className="caveat">"Add to cart" calls <i>your</i> API: POST /api/carts/ then POST /api/cart-items/. Your validation
          rules decide what happens.</p>
      )}
    </div>
  );
}
