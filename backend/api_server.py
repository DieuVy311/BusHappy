"""
BusHappy API Server
Provides REST API endpoints for bus stop and route information.
Features: nearby stops, route planning, real-time updates, accessibility filtering
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import math
import heapq
from collections import defaultdict

app = Flask(__name__)
CORS(app)

BASE_PATH = Path(__file__).parent / "Bus_route_data"
GTFS_PATH = Path(__file__).parent / "gtfs"

stops_df = pd.read_csv(GTFS_PATH / "stops.txt")
routes_df = pd.read_csv(GTFS_PATH / "routes.txt")
trips_df = pd.read_csv(GTFS_PATH / "trips.txt")
stop_times_df = pd.read_csv(GTFS_PATH / "stop_times.txt")

all_stops_df = pd.read_csv(BASE_PATH / "all_bus_stops_aggregated.csv")

stops_dict = stops_df.set_index('stop_id').to_dict('index')
routes_dict = routes_df.set_index('route_id').to_dict('index')

stop_routes_map = defaultdict(lambda: {'outbound': set(), 'inbound': set()})
for _, st in stop_times_df.iterrows():
    stop_id = int(st['stop_id'])
    trip = trips_df[trips_df['trip_id'] == st['trip_id']]
    if not trip.empty:
        route_id = trip.iloc[0]['route_id']
        direction = str(trip.iloc[0]['direction_id'])
        
        route = None
        if route_id in routes_dict:
            route = routes_dict[route_id]
        elif str(route_id) in routes_dict:
            route = routes_dict[str(route_id)]
        elif isinstance(route_id, str) and route_id.isdigit() and int(route_id) in routes_dict:
            route = routes_dict[int(route_id)]
        
        if route:
            route_number = route.get('route_short_name', str(route_id))
        else:
            route_number = str(route_id)
        
        if direction == '0':
            stop_routes_map[stop_id]['outbound'].add(route_number)
        else:
            stop_routes_map[stop_id]['inbound'].add(route_number)


def format_routes_display(stop_id: int) -> str:
    """
    Format route information showing both inbound and outbound routes.
    Returns formatted string like: "Outbound: 1, 65 | Inbound: 103, 146"
    """
    routes = stop_routes_map.get(stop_id, {'outbound': set(), 'inbound': set()})
    
    parts = []
    if routes['outbound']:
        outbound_routes = sorted(routes['outbound'], key=lambda x: int(x) if isinstance(x, str) and x.isdigit() else (x if isinstance(x, int) else 999))
        parts.append(f"Outbound: {', '.join(str(r) for r in outbound_routes)}")
    
    if routes['inbound']:
        inbound_routes = sorted(routes['inbound'], key=lambda x: int(x) if isinstance(x, str) and x.isdigit() else (x if isinstance(x, int) else 999))
        parts.append(f"Inbound: {', '.join(str(r) for r in inbound_routes)}")
    
    return ' | '.join(parts) if parts else ''


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on Earth.
    Returns distance in kilometers.
    """
    R = 6371  # Earth's radius in kilometers
    
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c


def get_upcoming_buses(stop_id: int, current_time: Optional[str] = None) -> List[Dict]:
    """
    Get upcoming buses for a specific stop.
    Returns list of trips with arrival times.
    """
    if current_time is None:
        current_time = datetime.now().strftime("%H:%M:%S")
    
    # Get all stop times for this stop
    stop_trips = stop_times_df[stop_times_df['stop_id'] == stop_id].copy()
    
    # Filter for upcoming times
    stop_trips['arrival_datetime'] = pd.to_datetime(stop_trips['arrival_time'], format='%H:%M:%S', errors='coerce')
    current_datetime = pd.to_datetime(current_time, format='%H:%M:%S')
    
    upcoming = stop_trips[stop_trips['arrival_datetime'] >= current_datetime].copy()
    upcoming = upcoming.sort_values('arrival_datetime').head(10)
    
    results = []
    for _, st in upcoming.iterrows():
        trip = trips_df[trips_df['trip_id'] == st['trip_id']].iloc[0]
        route = routes_dict.get(str(trip['route_id']), {})
        
        results.append({
            'route_number': route.get('route_short_name', 'N/A'),
            'route_name': route.get('route_long_name', 'N/A'),
            'headsign': trip.get('trip_headsign', ''),
            'arrival_time': st['arrival_time'],
            'direction': 'Outbound' if trip['direction_id'] == '0' else 'Inbound',
            'wheelchair_accessible': trip.get('wheelchair_accessible', '1') == '1'
        })
    
    return results


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'total_stops': len(stops_df),
        'total_routes': len(routes_df)
    })


@app.route('/api/stops/nearby', methods=['GET'])
def get_nearby_stops():
    """
    Get nearby bus stops within a specified radius.
    Query params: lat, lon, radius_km (default: 1), wheelchair_only (default: false)
    """
    try:
        lat = float(request.args.get('lat'))
        lon = float(request.args.get('lon'))
        radius_km = float(request.args.get('radius_km', 1.0))
        wheelchair_only = request.args.get('wheelchair_only', 'false').lower() == 'true'
        
        nearby_stops = []
        
        for _, stop in stops_df.iterrows():
            distance = haversine_distance(lat, lon, stop['stop_lat'], stop['stop_lon'])
            
            if distance <= radius_km:
                # Filter by wheelchair accessibility if needed
                if wheelchair_only and stop['wheelchair_boarding'] != 1:
                    continue
                
                stop_id = int(stop['stop_id'])
                routes_display = format_routes_display(stop_id)
                
                nearby_stops.append({
                    'stop_id': stop_id,
                    'stop_name': stop['stop_name'],
                    'stop_code': stop['stop_code'],
                    'distance_km': round(distance, 3),
                    'lat': stop['stop_lat'],
                    'lon': stop['stop_lon'],
                    'wheelchair_accessible': stop['wheelchair_boarding'] == 1,
                    'routes': routes_display
                })
        
        # Sort by distance
        nearby_stops.sort(key=lambda x: x['distance_km'])
        
        return jsonify({
            'success': True,
            'location': {'lat': lat, 'lon': lon},
            'radius_km': radius_km,
            'wheelchair_only': wheelchair_only,
            'stops': nearby_stops,
            'count': len(nearby_stops)
        })
    
    except ValueError as e:
        return jsonify({'success': False, 'error': 'Invalid parameters. Required: lat, lon'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/stops/<int:stop_id>', methods=['GET'])
def get_stop_details(stop_id: int):
    """Get detailed information about a specific stop."""
    try:
        stop = stops_dict.get(stop_id)
        
        if not stop:
            return jsonify({'success': False, 'error': 'Stop not found'}), 404
        
        # Get upcoming buses
        upcoming_buses = get_upcoming_buses(stop_id)
        
        # Get route information
        routes_display = format_routes_display(stop_id)
        
        return jsonify({
            'success': True,
            'stop': {
                'stop_id': stop_id,
                'stop_name': stop['stop_name'],
                'stop_code': stop['stop_code'],
                'lat': stop['stop_lat'],
                'lon': stop['stop_lon'],
                'wheelchair_accessible': stop['wheelchair_boarding'] == 1,
                'description': stop['stop_desc'],
                'routes': routes_display
            },
            'upcoming_buses': upcoming_buses
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/routes', methods=['GET'])
def get_all_routes():
    """Get list of all available routes."""
    try:
        wheelchair_only = request.args.get('wheelchair_only', 'false').lower() == 'true'
        
        routes_list = []
        for _, route in routes_df.iterrows():
            routes_list.append({
                'route_id': int(route['route_id']),
                'route_number': route['route_short_name'],
                'route_name': route['route_long_name'],
                'description': route['route_desc'],
                'color': route['route_color']
            })
        
        return jsonify({
            'success': True,
            'routes': routes_list,
            'count': len(routes_list)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/routes/<int:route_id>/stops', methods=['GET'])
def get_route_stops(route_id: int):
    """Get all stops for a specific route."""
    try:
        route_trips = trips_df[(trips_df['route_id'] == route_id) | (trips_df['route_id'] == str(route_id))]
        
        if route_trips.empty:
            return jsonify({'success': False, 'error': 'Route not found'}), 404
        
        outbound_trip = route_trips[route_trips['direction_id'] == '0'].iloc[0] if len(route_trips[route_trips['direction_id'] == '0']) > 0 else None
        inbound_trip = route_trips[route_trips['direction_id'] == '1'].iloc[0] if len(route_trips[route_trips['direction_id'] == '1']) > 0 else None
        
        result = {
            'success': True,
            'route_id': route_id,
            'route_info': routes_dict.get(str(route_id), {})
        }
        
        if outbound_trip is not None:
            outbound_stops = stop_times_df[stop_times_df['trip_id'] == outbound_trip['trip_id']].sort_values('stop_sequence')
            result['outbound_stops'] = [
                {
                    'stop_id': int(st['stop_id']),
                    'stop_name': stops_dict.get(st['stop_id'], {}).get('stop_name', 'Unknown'),
                    'sequence': int(st['stop_sequence']),
                    'lat': stops_dict.get(st['stop_id'], {}).get('stop_lat'),
                    'lon': stops_dict.get(st['stop_id'], {}).get('stop_lon')
                }
                for _, st in outbound_stops.iterrows()
            ]
        
        if inbound_trip is not None:
            inbound_stops = stop_times_df[stop_times_df['trip_id'] == inbound_trip['trip_id']].sort_values('stop_sequence')
            result['inbound_stops'] = [
                {
                    'stop_id': int(st['stop_id']),
                    'stop_name': stops_dict.get(st['stop_id'], {}).get('stop_name', 'Unknown'),
                    'sequence': int(st['stop_sequence']),
                    'lat': stops_dict.get(st['stop_id'], {}).get('stop_lat'),
                    'lon': stops_dict.get(st['stop_id'], {}).get('stop_lon')
                }
                for _, st in inbound_stops.iterrows()
            ]
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/plan', methods=['POST'])
def plan_route():
    """Plan a route between two locations using bus network."""
    try:
        data = request.get_json()
        
        from_lat = float(data['from_lat'])
        from_lon = float(data['from_lon'])
        to_lat = float(data['to_lat'])
        to_lon = float(data['to_lon'])
        wheelchair_only = data.get('wheelchair_accessible', False)
        
        start_stops = []
        end_stops = []
        
        for _, stop in stops_df.iterrows():
            if wheelchair_only and stop['wheelchair_boarding'] != 1:
                continue
            
            dist_from_start = haversine_distance(from_lat, from_lon, stop['stop_lat'], stop['stop_lon'])
            dist_from_end = haversine_distance(to_lat, to_lon, stop['stop_lat'], stop['stop_lon'])
            
            if dist_from_start <= 0.5:
                start_stops.append((dist_from_start, int(stop['stop_id']), stop['stop_name']))
            
            if dist_from_end <= 0.5:
                end_stops.append((dist_from_end, int(stop['stop_id']), stop['stop_name']))
        
        start_stops.sort()
        end_stops.sort()
        
        if not start_stops or not end_stops:
            return jsonify({
                'success': False,
                'error': 'No nearby stops found. Try increasing search radius.',
                'start_stops_found': len(start_stops),
                'end_stops_found': len(end_stops)
            }), 404
        
        routes_by_stop = defaultdict(set)
        for _, st in stop_times_df.iterrows():
            trip = trips_df[trips_df['trip_id'] == st['trip_id']]
            if not trip.empty:
                route_id = trip.iloc[0]['route_id']
                routes_by_stop[int(st['stop_id'])].add(str(route_id))
        
        best_routes = []
        
        for start_dist, start_stop_id, start_name in start_stops[:3]:
            for end_dist, end_stop_id, end_name in end_stops[:3]:
                if start_stop_id == end_stop_id:
                    continue
                
                start_routes = routes_by_stop.get(start_stop_id, set())
                end_routes = routes_by_stop.get(end_stop_id, set())
                common_routes = start_routes & end_routes
                
                for route_id in common_routes:
                    route = routes_dict.get(route_id, {})
                    best_routes.append({
                        'type': 'direct',
                        'start_stop': {
                            'id': start_stop_id,
                            'name': start_name,
                            'walk_distance_km': round(start_dist, 3)
                        },
                        'end_stop': {
                            'id': end_stop_id,
                            'name': end_name,
                            'walk_distance_km': round(end_dist, 3)
                        },
                        'route': {
                            'id': route_id,
                            'number': route.get('route_short_name', 'N/A'),
                            'name': route.get('route_long_name', 'N/A')
                        },
                        'total_walk_distance_km': round(start_dist + end_dist, 3)
                    })
        
        best_routes.sort(key=lambda x: x['total_walk_distance_km'])
        
        return jsonify({
            'success': True,
            'from': {'lat': from_lat, 'lon': from_lon},
            'to': {'lat': to_lat, 'lon': to_lon},
            'wheelchair_accessible': wheelchair_only,
            'routes': best_routes[:5],
            'count': len(best_routes)
        })
    
    except KeyError as e:
        return jsonify({'success': False, 'error': f'Missing required field: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/search', methods=['GET'])
def search_stops():
    """
    Search for stops by name or code.
    Query params: q (query string), wheelchair_only (optional)
    """
    try:
        query = request.args.get('q', '').lower()
        wheelchair_only = request.args.get('wheelchair_only', 'false').lower() == 'true'
        
        if len(query) < 2:
            return jsonify({
                'success': False,
                'error': 'Query must be at least 2 characters'
            }), 400
        
        results = []
        
        for _, stop in stops_df.iterrows():
            if wheelchair_only and stop['wheelchair_boarding'] != 1:
                continue
            
            # Search in name, code, and description
            if (query in stop['stop_name'].lower() or 
                query in str(stop['stop_code']).lower() or
                query in str(stop['stop_desc']).lower()):
                
                stop_id = int(stop['stop_id'])
                routes_display = format_routes_display(stop_id)
                
                results.append({
                    'stop_id': stop_id,
                    'stop_name': stop['stop_name'],
                    'stop_code': stop['stop_code'],
                    'lat': stop['stop_lat'],
                    'lon': stop['stop_lon'],
                    'wheelchair_accessible': stop['wheelchair_boarding'] == 1,
                    'description': stop['stop_desc'],
                    'routes': routes_display
                })
        
        return jsonify({
            'success': True,
            'query': query,
            'wheelchair_only': wheelchair_only,
            'results': results[:50],
            'count': len(results)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    print("🚌 BusHappy API Server Starting...")
    print(f"📊 Loaded {len(stops_df)} stops, {len(routes_df)} routes")
    print("🌐 Server running at http://localhost:5000")
    print("\n📝 Available endpoints:")
    print("  GET  /api/health - Health check")
    print("  GET  /api/stops/nearby?lat=X&lon=Y&radius_km=1&wheelchair_only=false")
    print("  GET  /api/stops/<stop_id>")
    print("  GET  /api/routes")
    print("  GET  /api/routes/<route_id>/stops")
    print("  GET  /api/search?q=query&wheelchair_only=false")
    print("  POST /api/plan - Route planning")
    print("\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
