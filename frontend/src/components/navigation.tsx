'use client';

/**
 * Navigation Component
 *
 * Main navigation bar for the AIRRA platform
 */
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Home, Bell, Users, Activity, BarChart3, UserCheck } from 'lucide-react';

const navItems = [
  { href: '/', label: 'Dashboard', icon: Home },
  { href: '/incidents', label: 'Incidents', icon: Activity },
  { href: '/notifications', label: 'Notifications', icon: Bell },
  { href: '/on-call', label: 'On-Call', icon: Users },
  { href: '/engineers', label: 'Engineers', icon: UserCheck },
  { href: '/analytics', label: 'Analytics', icon: BarChart3 },
];

export function Navigation() {
  const pathname = usePathname();

  return (
    <nav className="bg-white border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <Link href="/" className="flex items-center gap-2">
              <div className="bg-blue-600 rounded-lg p-2">
                <Activity className="h-6 w-6 text-white" />
              </div>
              <span className="text-xl font-bold text-gray-900">AIRRA</span>
            </Link>

            <div className="flex items-center gap-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                const isActive =
                  pathname === item.href || pathname?.startsWith(`${item.href}/`);

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={isActive ? 'page' : undefined}
                    className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-blue-50 text-blue-700'
                        : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                    }`}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="text-xs text-gray-500">Environment</p>
              <p className="text-sm font-medium text-gray-900">
                {process.env.NODE_ENV === 'production' ? 'Production' : 'Development'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
