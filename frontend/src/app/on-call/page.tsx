'use client';

/**
 * On-Call Dashboard
 *
 * Shows current on-call engineers across all services and their schedules
 */
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { apiClient } from '@/lib/api-client';
import { formatDistanceToNow } from 'date-fns';
import { Clock, Users, Calendar, AlertCircle } from 'lucide-react';

interface OnCallEngineer {
  engineer: {
    id: string;
    name: string;
    email: string;
    status: string;
    department: string | null;
  };
  schedule: {
    id: string;
    service: string | null;
    team: string | null;
    start_time: string;
    end_time: string;
    schedule_name: string | null;
  };
  priority: string;
}

async function getAllCurrentOnCall(): Promise<OnCallEngineer[]> {
  const response = await apiClient.get('/on-call/current/all');
  return response.data;
}

export default function OnCallDashboard() {
  const { data: onCallEngineers = [], isLoading, error } = useQuery({
    queryKey: ['on-call-current'],
    queryFn: getAllCurrentOnCall,
    refetchInterval: 60000, // Refresh every minute
    refetchIntervalInBackground: false, // Stop refreshing when tab is hidden
    retry: 3, // Retry failed requests 3 times
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000), // Exponential backoff
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <Clock className="h-12 w-12 animate-spin mx-auto mb-4 text-blue-600" />
          <p className="text-lg font-medium">Loading on-call data...</p>
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
            <CardTitle className="text-center">Error Loading Data</CardTitle>
            <CardDescription className="text-center">
              {error instanceof Error ? error.message : 'Failed to load on-call engineers'}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  const priorityColors = {
    PRIMARY: 'bg-green-600',
    SECONDARY: 'bg-yellow-600',
    TERTIARY: 'bg-orange-600',
  };

  const statusColors = {
    available: 'bg-green-100 text-green-800',
    busy: 'bg-yellow-100 text-yellow-800',
    on_leave: 'bg-gray-100 text-gray-800',
    offline: 'bg-red-100 text-red-800',
  };

  // Group by service
  const serviceGroups = onCallEngineers.reduce((acc, engineer) => {
    const service = engineer.schedule.service || 'General';
    if (!acc[service]) acc[service] = [];
    acc[service].push(engineer);
    return acc;
  }, {} as Record<string, OnCallEngineer[]>);

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
              <Users className="h-8 w-8" />
              On-Call Dashboard
            </h1>
            <p className="text-gray-600 mt-1">Current on-call engineers across all services</p>
          </div>
          <div className="text-right">
            <p className="text-sm text-gray-500">Auto-refreshing</p>
            <p className="text-xs text-gray-400">Every 60 seconds</p>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-600">Total On-Call</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">{onCallEngineers.length}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-600">Services</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">{Object.keys(serviceGroups).length}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-600">Primary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">
                {onCallEngineers.filter((e) => e.priority === 'PRIMARY').length}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-gray-600">Backup</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">
                {onCallEngineers.filter((e) => e.priority !== 'PRIMARY').length}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* On-Call Engineers by Service */}
        <div className="space-y-6">
          {Object.entries(serviceGroups).map(([service, engineers]) => (
            <Card key={service}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-xl">{service}</CardTitle>
                    <CardDescription>{engineers.length} engineer(s) on-call</CardDescription>
                  </div>
                  <Calendar className="h-6 w-6 text-gray-400" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {engineers
                    .sort((a, b) => {
                      const order = { PRIMARY: 0, SECONDARY: 1, TERTIARY: 2 };
                      return (
                        order[a.priority as keyof typeof order] -
                        order[b.priority as keyof typeof order]
                      );
                    })
                    .map((oncall) => (
                      <div
                        key={oncall.engineer.id}
                        className="flex items-center justify-between p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                      >
                        <div className="flex items-center gap-4">
                          <div
                            className={`w-3 h-3 rounded-full ${
                              priorityColors[oncall.priority as keyof typeof priorityColors]
                            }`}
                          />
                          <div>
                            <p className="font-semibold text-gray-900">
                              {oncall.engineer.name}
                              {oncall.engineer.department && (
                                <span className="ml-2 text-sm text-gray-500">
                                  ({oncall.engineer.department})
                                </span>
                              )}
                            </p>
                            <p className="text-sm text-gray-600">{oncall.engineer.email}</p>
                            {oncall.schedule.team && (
                              <p className="text-xs text-gray-500 mt-1">
                                Team: {oncall.schedule.team}
                              </p>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-4">
                          <div className="text-right">
                            <Badge className={priorityColors[oncall.priority as keyof typeof priorityColors]}>
                              {oncall.priority}
                            </Badge>
                            <Badge
                              className={`ml-2 ${
                                statusColors[
                                  oncall.engineer.status as keyof typeof statusColors
                                ]
                              }`}
                            >
                              {oncall.engineer.status.replace('_', ' ')}
                            </Badge>
                            <p className="text-xs text-gray-500 mt-2">
                              Until{' '}
                              {formatDistanceToNow(new Date(oncall.schedule.end_time), {
                                addSuffix: true,
                              })}
                            </p>
                            {oncall.schedule.schedule_name && (
                              <p className="text-xs text-gray-400 mt-1">
                                {oncall.schedule.schedule_name}
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {onCallEngineers.length === 0 && (
          <Card>
            <CardContent className="py-12">
              <div className="text-center text-gray-500">
                <Users className="h-16 w-16 mx-auto mb-4 opacity-30" />
                <p className="text-lg font-medium">No On-Call Engineers</p>
                <p className="text-sm mt-2">
                  No engineers are currently scheduled for on-call duty
                </p>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
