/** @type {import('next').NextConfig} */
const nextConfig = {
  // The desktop build runs with `next start`. Keeping output tracing disabled
  // avoids the Windows-only hang in "Collecting build traces". The Docker
  // image installs production dependencies instead of relying on standalone.
  experimental: { webpackBuildWorker: false },
};

export default nextConfig;
