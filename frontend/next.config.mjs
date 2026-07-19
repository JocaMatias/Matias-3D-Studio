/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // On Windows the parallel webpack build worker can publish the shared
  // server chunks after page-data collection has already started, producing
  // intermittent "Cannot find module ./<chunk>.js" failures. A single build
  // coordinator is slower by a few seconds but deterministic.
  experimental: { webpackBuildWorker: false },
};
export default nextConfig;
