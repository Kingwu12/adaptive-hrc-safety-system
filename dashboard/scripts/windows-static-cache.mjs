// vinext 0.0.50 indexes Windows static files using filesystem separators.
// Normalize cache keys to URL paths without modifying installed dependencies.
// Remove this compatibility shim when vinext normalizes its cache upstream.
import { StaticFileCache } from "../node_modules/vinext/dist/server/static-file-cache.js";

if (process.platform === "win32") {
  const create = StaticFileCache.create;
  StaticFileCache.create = async function (...args) {
    const cache = await create.apply(this, args);
    cache.entries = new Map(
      [...cache.entries].map(([key, entry]) => [key.replaceAll("\\", "/"), entry])
        .filter(([key]) => key !== "/.vite" && !key.startsWith("/.vite/")),
    );
    return cache;
  };
}
