"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  getSeverityColor,
  getStatusColor,
  formatRelativeTime,
  formatStatusText,
  cn
} from "@/lib/utils";
import { RefreshCw, Search, Filter, ChevronRight, Activity, AlertTriangle, Clock, CheckCircle } from "lucide-react";
import { Navbar } from "@/components/layout/Navbar";
import { QuickIncidentModal } from "@/components/incidents/QuickIncidentModal";

export default function IncidentsPage() {
  const [page, setPage] = useState(1);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const pageSize = 10;

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["incidents", page],
    queryFn: () => api.getIncidents({ page, page_size: pageSize }),
  });

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navbar />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Page Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
          <div>
            <h1 className="text-3xl font-extrabold tracking-tight">Incidents</h1>
            <p className="text-muted-foreground mt-1">
              Monitoring {data?.total || 0} total events across your infrastructure.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
              className="h-9 gap-2"
            >
              <RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} />
              Refresh
            </Button>
            <Button size="sm" className="h-9" onClick={() => setIsModalOpen(true)}>
              Report Incident
            </Button>
          </div>
        </div>

        {/* Filters & Search */}
        <Card className="mb-8 border-border/50 bg-card/50">
          <CardContent className="p-4 flex flex-wrap items-center gap-4">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input 
                type="text" 
                placeholder="Search incidents..." 
                className="w-full bg-background border border-border/50 rounded-lg py-2 pl-10 pr-4 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" className="gap-2 border-border/50">
                <Filter className="h-4 w-4" />
                Status
              </Button>
              <Button variant="outline" size="sm" className="gap-2 border-border/50">
                Severity
              </Button>
            </div>
          </CardContent>
        </Card>

        {isLoading ? (
          <div className="grid gap-4">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-24 w-full animate-pulse bg-muted rounded-xl" />
            ))}
          </div>
        ) : !data?.items.length ? (
          <div className="text-center py-24 border-2 border-dashed rounded-3xl bg-muted/20">
            <div className="bg-primary/10 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
              <CheckCircle className="h-8 w-8 text-primary" />
            </div>
            <h3 className="text-xl font-bold mb-2">No Incidents Found</h3>
            <p className="text-muted-foreground max-w-xs mx-auto">
              Great news! There are no incidents currently matching your filters.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {data.items.map((incident) => (
              <Card key={incident.id} className="group border-border/50 bg-card/50 hover:bg-card hover:border-primary/30 transition-all overflow-hidden">
                <Link href={`/incidents/${incident.id}`}>
                  <CardContent className="p-0">
                    <div className="flex flex-col md:flex-row md:items-center">
                      {/* Severity Indicator */}
                      <div className={cn(
                        "w-full md:w-2 h-2 md:h-auto self-stretch",
                        incident.severity === 'critical' ? 'bg-red-500' : 
                        incident.severity === 'high' ? 'bg-orange-500' : 
                        incident.severity === 'medium' ? 'bg-yellow-500' : 'bg-blue-500'
                      )} />
                      
                      <div className="flex-1 p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
                        <div className="space-y-1">
                          <div className="flex items-center gap-3">
                            <h3 className="text-lg font-bold group-hover:text-primary transition-colors">
                              {incident.title}
                            </h3>
                            <Badge variant="outline" className={cn("font-mono text-[10px]", getSeverityColor(incident.severity))}>
                              {incident.severity}
                            </Badge>
                          </div>
                          <p className="text-sm text-muted-foreground line-clamp-1 max-w-2xl">
                            {incident.description}
                          </p>
                          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mt-3 text-xs text-muted-foreground">
                            <span className="flex items-center gap-1.5 font-medium text-foreground">
                              <Activity className="h-3.5 w-3.5 text-primary" />
                              {incident.affected_service}
                            </span>
                            <span className="flex items-center gap-1.5">
                              <Clock className="h-3.5 w-3.5" />
                              {formatRelativeTime(incident.detected_at)}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center gap-6">
                          <div className="text-right hidden sm:block">
                            <Badge className={cn("px-3 py-1", getStatusColor(incident.status))}>
                              {formatStatusText(incident.status)}
                            </Badge>
                          </div>
                          <ChevronRight className="h-5 w-5 text-muted-foreground group-hover:text-primary group-hover:translate-x-1 transition-all" />
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Link>
              </Card>
            ))}

            {/* Pagination */}
            {data.pages > 1 && (
              <div className="flex items-center justify-between mt-10 pt-6 border-t border-border/50">
                <p className="text-sm text-muted-foreground">
                  Showing <span className="font-medium text-foreground">{(page - 1) * pageSize + 1}</span> to <span className="font-medium text-foreground">{Math.min(page * pageSize, data.total)}</span> of <span className="font-medium text-foreground">{data.total}</span> incidents
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="h-9"
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
                    disabled={page === data.pages}
                    className="h-9"
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {/* Quick Incident Modal */}
      <QuickIncidentModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} />
    </div>
  );
}