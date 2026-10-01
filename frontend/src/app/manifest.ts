import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Oldschool AFK Text MMO",
    short_name: "AFK MMO",
    description: "Oldschool AFK text MMORPG",
    start_url: "/game",
    scope: "/",
    display: "standalone",
    orientation: "any",
    background_color: "#0f1110",
    theme_color: "#0f1110",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
