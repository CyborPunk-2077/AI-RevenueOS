/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  poweredByHeader: false,
  // Only the BFF holds tokens; nothing secret is exposed to the browser bundle.
  env: {},
};

export default nextConfig;
