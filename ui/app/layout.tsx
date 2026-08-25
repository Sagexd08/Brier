import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Brier — confidence-calibrated slashing',
  description:
    'Every figure shown is either a committed measurement artifact or a live chain read. Nothing is simulated.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
