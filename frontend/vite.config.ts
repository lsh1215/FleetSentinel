import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { mockStreamPlugin } from "./server/mockStream";

export default defineConfig({
  plugins: [react(), mockStreamPlugin()],
  server: { port: 5173 },
  build: {
    target: "es2022",
    rollupOptions: {
      output: {
        // 벤더를 분리한다. 앱 코드는 자주 바뀌지만 지도·차트 라이브러리는 거의 안 바뀌므로,
        // 한 청크에 묶어두면 앱을 배포할 때마다 1.3MB를 다시 받게 된다.
        // Rerun 뷰어(wasm 29.8MB)는 동적 import라 자동으로 별도 청크가 된다 — 여기 넣지 않는다.
        manualChunks: {
          maplibre: ["maplibre-gl"],
          charts: ["uplot"],
          react: ["react", "react-dom", "react-dom/client"],
        },
      },
    },
  },
});
