'use client';

/**
 * AIRRA Dashboard - Home Page
 *
 * Main dashboard showing system overview and quick links
 */
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { apiClient } from '@/lib/api-client';
import {
  Activity,
  Users,
  Bell,
  TrendingUp,
  ArrowRight,
  AlertCircle,
  CheckCircle,
  Clock,
  Zap,
} from 'lucide-react';

async function getDashboardStats() {
  const [incidentsRes, notificationsRes, onCallRes] = await Promise.all([
    apiClient.get('/incidents/', { params: { page: 1, page_size: 5 } }),
    apiClient.get('/notifications/stats/summary'),
    apiClient.get('/on-call/current/all'),
  ]);

  return {
    incidents: incidentsRes.data,
    notificationStats: notificationsRes.data,
    onCallEngineers: onCallRes.data,
  };
}

export default function HomePage() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: getDashboardStats,
    refetchInterval: 30000, // Refresh every 30 seconds
    refetchIntervalInBackground: false, // Stop refreshing when tab is hidden
    retry: 3, // Retry failed requests 3 times
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000), // Exponential backoff
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <Activity className="h-12 w-12 animate-pulse mx-auto mb-4 text-blue-600" />
          <p className="text-lg font-medium">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Card className="max-w-md">
          <CardHeader>
            <AlertCircle className="h-12 w-12 text-red-600 mx-auto mb-2" />
            <CardTitle className="text-center">Connection Error</CardTitle>
            <CardDescription className="text-center">
              Unable to connect to AIRRA backend. Please ensure the backend is running.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-center">
            <p className="text-sm text-gray-600 mb-4">
              Expected backend URL: {process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}
            </p>
            <Button onClick={() => refetch()} disabled={isLoading}>
              {isLoading ? 'Retrying...' : 'Retry'}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { incidents, notificationStats, onCallEngineers } = data || {};
  const recentIncidents = incidents?.items || [];
  const stats = notificationStats || {};
  const onCall = onCallEngineers || [];

  // Calculate open incidents
  const openIncidents =
    recentIncidents.filter((i: any) => ['open', 'investigating'].includes(i.status)).length || 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 py-12">
        {/* Hero Section */}
        <div className="mb-12">
          <h1 className="text-4xl font-extrabold text-gray-900 mb-4">
            Autonomous Incident Response
          </h1>
          <p className="text-xl text-gray-600">
            AI-powered incident management with intelligent engineer notification
          </p>
        </div>

        {/* Key Metrics */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-12">
          <Card className="hover:shadow-lg transition-shadow">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-gray-600">
                  Active Incidents
                </CardTitle>
                <Activity className="h-5 w-5 text-blue-600" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-gray-900">{openIncidents}</div>
              <p className="text-xs text-gray-500 mt-1">Currently being handled</p>
            </CardContent>
          </Card>

          <Card className="hover:shadow-lg transition-shadow">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-gray-600">On-Call</CardTitle>
                <Users className="h-5 w-5 text-green-600" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-gray-900">{onCall.length}</div>
              <p className="text-xs text-gray-500 mt-1">Engineers available</p>
            </CardContent>
          </Card>

          <Card className="hover:shadow-lg transition-shadow">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-gray-600">
                  Notifications
                </CardTitle>
                <Bell className="h-5 w-5 text-purple-600" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-gray-900">
                {stats.total_acknowledged || 0}
              </div>
              <p className="text-xs text-gray-500 mt-1">
                {stats.total_sent || 0} sent total
              </p>
            </CardContent>
          </Card>

          <Card className="hover:shadow-lg transition-shadow">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-gray-600">
                  SLA Compliance
                </CardTitle>
                <TrendingUp className="h-5 w-5 text-orange-600" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-gray-900">
                {stats.sla_compliance_rate !== null && stats.sla_compliance_rate !== undefined
                  ? `${Math.round(stats.sla_compliance_rate * 100)}%`
                  : 'N/A'}
              </div>
              <p className="text-xs text-gray-500 mt-1">Response time SLA</p>
            </CardContent>
          </Card>
        </div>

        {/* Quick Links */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-12">
          <Link href="/incidents" className="group">
            <Card className="h-full hover:shadow-lg transition-all hover:border-blue-300">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="bg-blue-100 rounded-lg p-3">
                      <Activity className="h-6 w-6 text-blue-600" />
                    </div>
                    <div>
                      <CardTitle>Incident Management</CardTitle>
                      <CardDescription>View and manage active incidents</CardDescription>
                    </div>
                  </div>
                  <ArrowRight className="h-5 w-5 text-gray-400 group-hover:text-blue-600 transition-colors" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">Open:</span>
                    <Badge className="bg-red-100 text-red-800">{openIncidents}</Badge>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">Total:</span>
                    <span className="font-medium">{incidents?.total || 0}</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>

          <Link href="/on-call" className="group">
            <Card className="h-full hover:shadow-lg transition-all hover:border-green-300">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="bg-green-100 rounded-lg p-3">
                      <Users className="h-6 w-6 text-green-600" />
                    </div>
                    <div>
                      <CardTitle>On-Call Schedule</CardTitle>
                      <CardDescription>Current on-call engineers</CardDescription>
                    </div>
                  </div>
                  <ArrowRight className="h-5 w-5 text-gray-400 group-hover:text-green-600 transition-colors" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">Total On-Call:</span>
                    <Badge className="bg-green-100 text-green-800">{onCall.length}</Badge>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">Primary:</span>
                    <span className="font-medium">
                      {onCall.filter((e: any) => e.priority === 'PRIMARY').length}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>

          <Link href="/notifications" className="group">
            <Card className="h-full hover:shadow-lg transition-all hover:border-purple-300">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="bg-purple-100 rounded-lg p-3">
                      <Bell className="h-6 w-6 text-purple-600" />
                    </div>
                    <div>
                      <CardTitle>Notifications</CardTitle>
                      <CardDescription>Track engineer notifications</CardDescription>
                    </div>
                  </div>
                  <ArrowRight className="h-5 w-5 text-gray-400 group-hover:text-purple-600 transition-colors" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">Acknowledged:</span>
                    <Badge className="bg-purple-100 text-purple-800">
                      {stats.total_acknowledged || 0}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">Avg Response:</span>
                    <span className="font-medium">
                      {stats.average_response_time_seconds
                        ? `${Math.round(stats.average_response_time_seconds / 60)}m`
                        : 'N/A'}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>

          <Link href="/analytics" className="group">
            <Card className="h-full hover:shadow-lg transition-all hover:border-orange-300">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="bg-orange-100 rounded-lg p-3">
                      <TrendingUp className="h-6 w-6 text-orange-600" />
                    </div>
                    <div>
                      <CardTitle>Analytics</CardTitle>
                      <CardDescription>System performance metrics</CardDescription>
                    </div>
                  </div>
                  <ArrowRight className="h-5 w-5 text-gray-400 group-hover:text-orange-600 transition-colors" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">SLA Met:</span>
                    <span className="font-medium">
                      {stats.sla_compliance_rate
                        ? `${Math.round(stats.sla_compliance_rate * 100)}%`
                        : 'N/A'}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">Escalation Rate:</span>
                    <span className="font-medium">
                      {stats.escalation_rate
                        ? `${Math.round(stats.escalation_rate * 100)}%`
                        : 'N/A'}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        </div>

        {/* Recent Incidents */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <Zap className="h-5 w-5 text-yellow-600" />
                  Recent Incidents
                </CardTitle>
                <CardDescription>Latest 5 incidents across all services</CardDescription>
              </div>
              <Link href="/incidents">
                <Button variant="outline" size="sm">
                  View All
                  <ArrowRight className="h-4 w-4 ml-2" />
                </Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            {recentIncidents.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                <CheckCircle className="h-16 w-16 mx-auto mb-4 opacity-30" />
                <p className="text-lg font-medium">No Active Incidents</p>
                <p className="text-sm mt-2">All systems operational</p>
              </div>
            ) : (
              <div className="space-y-3">
                {recentIncidents.map((incident: any) => {
                  const severityColors = {
                    critical: 'bg-red-600',
                    high: 'bg-orange-600',
                    medium: 'bg-yellow-600',
                    low: 'bg-blue-600',
                  };

                  const statusColors = {
                    open: 'bg-red-100 text-red-800',
                    investigating: 'bg-yellow-100 text-yellow-800',
                    mitigating: 'bg-blue-100 text-blue-800',
                    resolved: 'bg-green-100 text-green-800',
                    closed: 'bg-gray-100 text-gray-800',
                  };

                  return (
                    <Link
                      key={incident.id}
                      href={`/incidents/${incident.id}`}
                      className="block border border-gray-200 rounded-lg p-4 hover:bg-gray-50 transition-colors"
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-start gap-3 flex-1">
                          <div
                            className={`w-2 h-2 rounded-full mt-2 ${
                              severityColors[incident.severity as keyof typeof severityColors]
                            }`}
                          />
                          <div className="flex-1">
                            <p className="font-semibold text-gray-900">{incident.title}</p>
                            <p className="text-sm text-gray-600 mt-1">
                              {incident.affected_service}
                            </p>
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          <Badge
                            className={statusColors[incident.status as keyof typeof statusColors]}
                          >
                            {incident.status}
                          </Badge>
                          <div className="flex items-center gap-1 text-xs text-gray-500">
                            <Clock className="h-3 w-3" />
                            <span>
                              {new Date(incident.detected_at).toLocaleDateString()}
                            </span>
                          </div>
                        </div>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
