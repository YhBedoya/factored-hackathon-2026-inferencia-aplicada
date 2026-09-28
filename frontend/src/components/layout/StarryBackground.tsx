// Purely decorative (brand.md "Visual identity": stars outside the chat area
// only). CSS-only so it never needs an asset or a string from `t()`. It sits
// behind everything at a fixed position; the chat panel (T4) paints its own
// opaque background on top of it, so the stars never compete with legibility
// there.
const STAR_LAYER = [
	"radial-gradient(1px 1px at 20px 30px, rgba(255,255,255,0.9), transparent)",
	"radial-gradient(1px 1px at 120px 90px, rgba(255,255,255,0.65), transparent)",
	"radial-gradient(1.5px 1.5px at 70px 160px, rgba(255,255,255,0.8), transparent)",
	"radial-gradient(1px 1px at 210px 50px, rgba(255,255,255,0.5), transparent)",
	"radial-gradient(1.5px 1.5px at 270px 210px, rgba(255,255,255,0.85), transparent)",
	"radial-gradient(1px 1px at 330px 130px, rgba(255,255,255,0.45), transparent)",
	"radial-gradient(1px 1px at 40px 220px, rgba(255,255,255,0.6), transparent)",
].join(", ");

export function StarryBackground() {
	return (
		<div
			aria-hidden="true"
			className="pointer-events-none fixed inset-0 z-0 bg-bg"
			style={{
				backgroundImage: STAR_LAYER,
				backgroundSize: "360px 240px",
				backgroundRepeat: "repeat",
			}}
		/>
	);
}
