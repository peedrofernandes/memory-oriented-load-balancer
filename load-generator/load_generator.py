#!/usr/bin/env python3
"""
Load Generator for TCP/HTTP Load Balancer

This script generates configurable concurrent load on the load balancer
to test performance and distribution capabilities.
"""

import asyncio
import aiohttp
import argparse
import json
import time
import statistics
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
import threading
import signal
import sys
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import re
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs, urlencode
import random
import uuid


@dataclass
class DashSegment:
    """Information about a DASH segment"""
    url: str
    segment_type: str  # 'init' or 'media'
    representation_id: str
    segment_number: Optional[int] = None

@dataclass
class RequestResult:
    """Result of a single request"""
    success: bool
    response_time: float
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    timestamp: float = 0.0
    url: Optional[str] = None
    segment_type: Optional[str] = None


@dataclass
class LoadTestResults:
    """Aggregated results of the load test"""
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_time: float
    requests_per_second: float
    avg_response_time: float
    min_response_time: float
    max_response_time: float
    p50_response_time: float
    p95_response_time: float
    p99_response_time: float
    error_rate: float
    errors: Dict[str, int]


class DashManifestParser:
    """Parser for MPEG-DASH manifest files"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.logger = logging.getLogger('DashManifestParser')
    
    async def fetch_and_parse_manifest(self, session: aiohttp.ClientSession, manifest_url: str) -> List[DashSegment]:
        """Fetch the DASH manifest and parse segment URLs"""
        self.logger.info(f"Fetching DASH manifest from: {manifest_url}")
        
        try:
            async with session.get(manifest_url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to fetch manifest: HTTP {response.status}")
                
                manifest_content = await response.text()
                return self.parse_manifest(manifest_content, manifest_url)
                
        except Exception as e:
            self.logger.error(f"Error fetching manifest: {e}")
            raise
    
    def parse_manifest(self, manifest_content: str, manifest_url: str) -> List[DashSegment]:
        """Parse DASH manifest XML and extract segment URLs"""
        segments = []
        
        try:
            # Parse XML with namespace handling
            root = ET.fromstring(manifest_content)
            
            # Define namespace map for DASH
            ns = {'dash': 'urn:mpeg:dash:schema:mpd:2011'}
            
            # Find all adaptation sets
            adaptation_sets = root.findall('.//dash:AdaptationSet', ns)
            
            for adaptation_set in adaptation_sets:
                representations = adaptation_set.findall('dash:Representation', ns)
                
                for representation in representations:
                    rep_id = representation.get('id', 'unknown')
                    
                    # Find segment template
                    segment_template = representation.find('dash:SegmentTemplate', ns)
                    if segment_template is not None:
                        init_template = segment_template.get('initialization')
                        media_template = segment_template.get('media')
                        start_number = int(segment_template.get('startNumber', '1'))
                        
                        # Calculate base URL for segments
                        base_segment_url = urljoin(manifest_url, './')
                        
                        # Add initialization segment
                        if init_template:
                            init_url = init_template.replace('$RepresentationID$', rep_id)
                            segments.append(DashSegment(
                                url=urljoin(base_segment_url, init_url),
                                segment_type='init',
                                representation_id=rep_id
                            ))
                        
                        # Find segment timeline to get number of segments
                        segment_timeline = segment_template.find('dash:SegmentTimeline', ns)
                        if segment_timeline is not None:
                            s_elements = segment_timeline.findall('dash:S', ns)
                            segment_number = start_number
                            
                            for s_element in s_elements:
                                repeat = int(s_element.get('r', '0'))
                                # Add one segment for the base S element
                                for _ in range(repeat + 1):
                                    if media_template:
                                        media_url = (media_template
                                                   .replace('$RepresentationID$', rep_id)
                                                   .replace('$Number%05d$', f'{segment_number:05d}'))
                                        segments.append(DashSegment(
                                            url=urljoin(base_segment_url, media_url),
                                            segment_type='media',
                                            representation_id=rep_id,
                                            segment_number=segment_number
                                        ))
                                    segment_number += 1
            
            self.logger.info(f"Parsed {len(segments)} segments from manifest")
            return segments
            
        except ET.ParseError as e:
            self.logger.error(f"Failed to parse manifest XML: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error parsing manifest: {e}")
            raise


class LoadGenerator:
    """Main load generator class"""
    
    def __init__(self, target_url: str, concurrent_users: int = 10, 
                 total_requests: int = 100, duration: Optional[int] = None,
                 request_delay: float = 0.0, timeout: float = 30.0, 
                 log_level: str = "INFO", manifest_path: str = "/Static/Earth/manifest.mpd",
                 simulate_dash: bool = True, segment_interval: float = 2.0,
                 disable_cache: bool = True, max_earth_directories: int = 100):
        self.target_url = target_url
        self.concurrent_users = concurrent_users
        self.total_requests = total_requests
        self.duration = duration
        self.request_delay = request_delay
        self.timeout = timeout
        self.manifest_path = manifest_path
        self.simulate_dash = simulate_dash
        self.segment_interval = segment_interval
        self.disable_cache = disable_cache
        self.max_earth_directories = max_earth_directories
        
        self.results: List[RequestResult] = []
        self.results_lock = threading.Lock()
        self.start_time = 0.0
        self.end_time = 0.0
        self.stop_event = threading.Event()
        
        # DASH-specific attributes
        self.dash_segments: List[DashSegment] = []
        self.segments_lock = threading.Lock()
        self.manifest_parser = DashManifestParser(target_url)
        
        # Setup logging
        self._setup_logging(log_level)
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _add_cache_busting(self, url: str) -> str:
        """Add cache-busting parameters to URL to ensure fresh requests"""
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        
        # Add multiple cache-busting parameters
        query_params['_cb'] = [str(int(time.time() * 1000))]  # Current timestamp in ms
        query_params['_rnd'] = [str(random.randint(10000, 99999))]  # Random number
        query_params['_uid'] = [str(uuid.uuid4())[:8]]  # Unique identifier
        
        # Rebuild URL with cache-busting parameters
        new_query = urlencode(query_params, doseq=True)
        return urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment
        ))
    
    def _setup_logging(self, log_level: str):
        """Setup logging configuration"""
        self.logger = logging.getLogger('LoadGenerator')
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Create console handler
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}. Shutting down gracefully...")
        print(f"\nReceived signal {signum}. Shutting down gracefully...")
        self.stop_event.set()
    
    async def _make_request(self, session: aiohttp.ClientSession, request_id: int, 
                           url: Optional[str] = None, segment_type: Optional[str] = None) -> RequestResult:
        """Make a single HTTP request with cache-busting"""
        start_time = time.time()
        timestamp = start_time
        base_url = url if url else self.target_url
        
        # Conditionally add cache-busting parameters and headers
        if self.disable_cache:
            request_url = self._add_cache_busting(base_url)
            # Headers to disable all forms of caching
            no_cache_headers = {
                'Cache-Control': 'no-cache, no-store, must-revalidate, max-age=0',
                'Pragma': 'no-cache',
                'Expires': '0',
                'If-Modified-Since': 'Thu, 01 Jan 1970 00:00:00 GMT',
                'If-None-Match': '*',
                'User-Agent': f'LoadGenerator-{request_id}-{int(time.time())}'
            }
        else:
            request_url = base_url
            no_cache_headers = {
                'User-Agent': f'LoadGenerator-{request_id}'
            }
        
        try:
            async with session.get(
                request_url,
                headers=no_cache_headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                await response.read()  # Consume the response body
                end_time = time.time()
                
                # Log successful requests at DEBUG level
                self.logger.debug(f"Request {request_id}: SUCCESS - Status: {response.status}, "
                                f"Time: {(end_time - start_time)*1000:.2f}ms - URL: {request_url} "
                                f"Type: {segment_type or 'standard'}")
                
                return RequestResult(
                    success=True,
                    response_time=end_time - start_time,
                    status_code=response.status,
                    timestamp=timestamp,
                    url=request_url,
                    segment_type=segment_type
                )
                
        except asyncio.TimeoutError:
            end_time = time.time()
            error_msg = f"Request timeout after {self.timeout}s"
            self.logger.warning(f"Request {request_id}: {error_msg} - URL: {request_url}")
            return RequestResult(
                success=False,
                response_time=end_time - start_time,
                error_message="Timeout",
                timestamp=timestamp,
                url=request_url,
                segment_type=segment_type
            )
        except aiohttp.ClientConnectorError as e:
            end_time = time.time()
            error_msg = f"Connection error: {str(e)}"
            self.logger.error(f"Request {request_id}: {error_msg} - URL: {request_url}")
            return RequestResult(
                success=False,
                response_time=end_time - start_time,
                error_message=f"Connection Error: {str(e)}",
                timestamp=timestamp,
                url=request_url,
                segment_type=segment_type
            )
        except aiohttp.ClientResponseError as e:
            end_time = time.time()
            error_msg = f"HTTP {e.status} error: {str(e)}"
            self.logger.error(f"Request {request_id}: {error_msg} - URL: {request_url}")
            return RequestResult(
                success=False,
                response_time=end_time - start_time,
                error_message=f"HTTP Error {e.status}: {str(e)}",
                timestamp=timestamp,
                url=request_url,
                segment_type=segment_type
            )
        except aiohttp.ClientError as e:
            end_time = time.time()
            error_msg = f"Client error: {type(e).__name__}: {str(e)}"
            self.logger.error(f"Request {request_id}: {error_msg} - URL: {request_url}")
            return RequestResult(
                success=False,
                response_time=end_time - start_time,
                error_message=f"Client Error: {type(e).__name__}: {str(e)}",
                timestamp=timestamp,
                url=request_url,
                segment_type=segment_type
            )
        except Exception as e:
            end_time = time.time()
            error_msg = f"Unexpected error: {type(e).__name__}: {str(e)}"
            self.logger.error(f"Request {request_id}: {error_msg} - URL: {request_url}")
            return RequestResult(
                success=False,
                response_time=end_time - start_time,
                error_message=f"Unexpected Error: {str(e)}",
                timestamp=timestamp,
                url=request_url,
                segment_type=segment_type
            )
    
    async def _worker(self, worker_id: int, session: aiohttp.ClientSession):
        """Worker coroutine that makes requests"""
        request_count = 0
        worker_start_time = time.time()
        
        self.logger.debug(f"Worker {worker_id}: Started")
        
        if self.simulate_dash:
            await self._dash_worker(worker_id, session)
        else:
            await self._standard_worker(worker_id, session)
        
        worker_end_time = time.time()
        self.logger.debug(f"Worker {worker_id}: Completed {request_count} requests in "
                         f"{worker_end_time - worker_start_time:.2f}s")
    
    async def _standard_worker(self, worker_id: int, session: aiohttp.ClientSession):
        """Standard worker that makes simple requests to target URL"""
        request_count = 0
        
        while not self.stop_event.is_set():
            # Check if we've reached the total request limit
            with self.results_lock:
                if len(self.results) >= self.total_requests:
                    break
            
            # Check if we've exceeded the duration limit
            if self.duration and (time.time() - self.start_time) >= self.duration:
                break
            
            # Make the request with unique ID per worker
            unique_request_id = f"{worker_id}-{request_count}"
            result = await self._make_request(session, unique_request_id)
            
            # Store the result
            with self.results_lock:
                self.results.append(result)
                total_completed = len(self.results)
                
                # Log progress every 100 requests or on errors
                if total_completed % 100 == 0 or not result.success:
                    elapsed = time.time() - self.start_time
                    rate = total_completed / elapsed if elapsed > 0 else 0
                    self.logger.info(f"Progress: {total_completed}/{self.total_requests} requests completed "
                                   f"({rate:.1f} req/s) - Errors: {sum(1 for r in self.results if not r.success)}")
            
            request_count += 1
            
            # Optional delay between requests
            if self.request_delay > 0:
                await asyncio.sleep(self.request_delay)
    
    async def _dash_worker(self, worker_id: int, session: aiohttp.ClientSession):
        """DASH simulation worker that continuously fetches segments in a loop"""
        # Randomly select an Earth directory (Earth1 to Earth{max_earth_directories})
        earth_number = random.randint(1, self.max_earth_directories)
        selected_earth_dir = f"Earth{earth_number}"
        
        # Construct manifest path for the selected Earth directory
        manifest_path = f"/Static/{selected_earth_dir}/manifest.mpd"
        manifest_url = urljoin(self.target_url, manifest_path)
        
        self.logger.debug(f"Worker {worker_id}: Starting DASH client simulation for {selected_earth_dir}")
        self.logger.info(f"Worker {worker_id}: Selected Earth directory '{selected_earth_dir}'")
        
        # Fetch manifest once at the beginning
        manifest_result = await self._make_request(session, f"{worker_id}-manifest", 
                                                 manifest_url, "manifest")
        with self.results_lock:
            self.results.append(manifest_result)
            if len(self.results) >= self.total_requests:
                return
        
        if not manifest_result.success:
            self.logger.warning(f"Worker {worker_id}: Manifest request failed, worker stopping")
            return
        
        # Get segments for this specific Earth directory (don't use global cache for multi-directory)
        try:
            segments = await self.manifest_parser.fetch_and_parse_manifest(session, manifest_url)
        except Exception as e:
            self.logger.error(f"Worker {worker_id}: Failed to parse manifest for {selected_earth_dir}: {e}")
            return
        
        if not segments:
            self.logger.error(f"Worker {worker_id}: No segments found in manifest")
            return
        
        # Separate init and media segments
        init_segments = [s for s in segments if s.segment_type == 'init']
        media_segments = [s for s in segments if s.segment_type == 'media']
        
        # Fetch initialization segments once
        for i, segment in enumerate(init_segments):
            if self.stop_event.is_set():
                return
            with self.results_lock:
                if len(self.results) >= self.total_requests:
                    return
            
            result = await self._make_request(session, f"{worker_id}-init-{i}", 
                                            segment.url, f"init-{segment.representation_id}")
            with self.results_lock:
                self.results.append(result)
        
        # Now continuously loop through media segments
        segment_index = 0
        request_count = 0
        
        while not self.stop_event.is_set():
            # Check if we've reached the total request limit
            with self.results_lock:
                if len(self.results) >= self.total_requests:
                    break
            
            # Check if we've exceeded the duration limit
            if self.duration and (time.time() - self.start_time) >= self.duration:
                break
            
            # Select current segment (cycle through all media segments)
            if media_segments:
                current_segment = media_segments[segment_index % len(media_segments)]
                segment_index += 1
                
                # Make request for current segment
                result = await self._make_request(
                    session, 
                    f"{worker_id}-media-{request_count}", 
                    current_segment.url, 
                    f"media-{current_segment.representation_id}-{current_segment.segment_number}"
                )
                
                with self.results_lock:
                    self.results.append(result)
                    total_completed = len(self.results)
                    
                    # Log progress every 50 requests or on errors for DASH
                    if total_completed % 50 == 0 or not result.success:
                        elapsed = time.time() - self.start_time
                        rate = total_completed / elapsed if elapsed > 0 else 0
                        self.logger.info(f"Progress: {total_completed}/{self.total_requests} requests completed "
                                       f"({rate:.1f} req/s) - Errors: {sum(1 for r in self.results if not r.success)} "
                                       f"- Worker {worker_id} on segment {segment_index}")
                
                request_count += 1
                
                # Simulate realistic segment download interval
                segment_delay = max(0.5, self.request_delay) if self.request_delay > 0 else self.segment_interval
                await asyncio.sleep(segment_delay)
            else:
                self.logger.warning(f"Worker {worker_id}: No media segments available")
                break
        
        self.logger.debug(f"Worker {worker_id}: Completed {request_count} segment requests")
    
    async def _simulate_dash_session(self, worker_id: int, session: aiohttp.ClientSession, session_count: int):
        """Simulate a complete DASH client session"""
        session_id = f"{worker_id}-{session_count}"
        
        # Step 1: Fetch manifest
        manifest_url = urljoin(self.target_url, self.manifest_path)
        self.logger.debug(f"Worker {worker_id}: Starting DASH session {session_count}")
        
        # Request manifest
        manifest_result = await self._make_request(session, f"{session_id}-manifest", 
                                                 manifest_url, "manifest")
        with self.results_lock:
            self.results.append(manifest_result)
            if len(self.results) >= self.total_requests:
                return
        
        if not manifest_result.success:
            self.logger.warning(f"Worker {worker_id}: Manifest request failed, skipping session")
            return
        
        # Step 2: Get segments (use cached segments if available)
        segments = []
        with self.segments_lock:
            if not self.dash_segments:
                try:
                    self.dash_segments = await self.manifest_parser.fetch_and_parse_manifest(session, manifest_url)
                except Exception as e:
                    self.logger.error(f"Worker {worker_id}: Failed to parse manifest: {e}")
                    return
            segments = self.dash_segments.copy()
        
        # Step 3: Request segments (init segments first, then media segments)
        init_segments = [s for s in segments if s.segment_type == 'init']
        media_segments = [s for s in segments if s.segment_type == 'media']
        
        # Request initialization segments
        for i, segment in enumerate(init_segments):
            if self.stop_event.is_set():
                break
            with self.results_lock:
                if len(self.results) >= self.total_requests:
                    break
            
            result = await self._make_request(session, f"{session_id}-init-{i}", 
                                            segment.url, f"init-{segment.representation_id}")
            with self.results_lock:
                self.results.append(result)
        
        # Request a subset of media segments (simulate progressive download)
        # Take first few segments from each representation to simulate beginning of playback
        segments_per_rep = 3  # Simulate downloading first 3 segments per representation
        for rep_id in set(s.representation_id for s in media_segments):
            rep_segments = [s for s in media_segments if s.representation_id == rep_id][:segments_per_rep]
            
            for i, segment in enumerate(rep_segments):
                if self.stop_event.is_set():
                    break
                with self.results_lock:
                    if len(self.results) >= self.total_requests:
                        break
                
                result = await self._make_request(session, f"{session_id}-media-{rep_id}-{i}", 

                                                segment.url, f"media-{segment.representation_id}")
                with self.results_lock:
                    self.results.append(result)
                    total_completed = len(self.results)
                    
                    # Log progress every 50 requests or on errors for DASH
                    if total_completed % 50 == 0 or not result.success:
                        elapsed = time.time() - self.start_time
                        rate = total_completed / elapsed if elapsed > 0 else 0
                        self.logger.info(f"Progress: {total_completed}/{self.total_requests} requests completed "
                                       f"({rate:.1f} req/s) - Errors: {sum(1 for r in self.results if not r.success)}")
                
                # Small delay between segments to simulate realistic client behavior
                await asyncio.sleep(0.1)
    
    async def _run_async_load_test(self):
        """Run the asynchronous load test"""
        # Configure session with connection pooling
        connector = aiohttp.TCPConnector(
            limit=self.concurrent_users * 2,  # Total connection pool size
            limit_per_host=self.concurrent_users * 2,  # Per-host limit
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
        
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        
        # Default headers - conditionally disable caching at session level
        default_headers = {'User-Agent': 'LoadGenerator/1.0'}
        if self.disable_cache:
            default_headers.update({
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            })
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=default_headers
        ) as session:
            # Create worker tasks
            tasks = []
            for i in range(self.concurrent_users):
                task = asyncio.create_task(self._worker(i, session))
                tasks.append(task)
            
            # Wait for all tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def run_load_test(self) -> LoadTestResults:
        """Run the load test and return results"""
        self.logger.info(f"Starting load test with {self.concurrent_users} concurrent users")
        self.logger.info(f"Target URL: {self.target_url}")
        self.logger.info(f"Total requests: {self.total_requests}")
        if self.duration:
            self.logger.info(f"Duration: {self.duration} seconds")
        self.logger.info(f"Request timeout: {self.timeout} seconds")
        
        print(f"Starting load test...")
        print(f"Target URL: {self.target_url}")
        print(f"Concurrent users: {self.concurrent_users}")
        print(f"Total requests: {self.total_requests}")
        if self.duration:
            print(f"Duration: {self.duration} seconds")
        print(f"Request timeout: {self.timeout} seconds")
        print(f"Log level: {self.logger.level}")
        print("-" * 50)
        
        self.start_time = time.time()
        
        # Run the async load test
        try:
            asyncio.run(self._run_async_load_test())
        except KeyboardInterrupt:
            print("\nLoad test interrupted by user")
        
        self.end_time = time.time()
        
        return self._calculate_results()
    
    def _calculate_results(self) -> LoadTestResults:
        """Calculate and return test results"""
        if not self.results:
            return LoadTestResults(
                total_requests=0, successful_requests=0, failed_requests=0,
                total_time=0, requests_per_second=0, avg_response_time=0,
                min_response_time=0, max_response_time=0,
                p50_response_time=0, p95_response_time=0, p99_response_time=0,
                error_rate=0, errors={}
            )
        
        total_requests = len(self.results)
        successful_requests = sum(1 for r in self.results if r.success)
        failed_requests = total_requests - successful_requests
        total_time = self.end_time - self.start_time
        
        # Calculate response time statistics
        response_times = [r.response_time for r in self.results]
        response_times.sort()
        
        # Calculate percentiles
        def percentile(data, p):
            if not data:
                return 0
            k = (len(data) - 1) * p / 100
            f = int(k)
            c = k - f
            if f + 1 < len(data):
                return data[f] * (1 - c) + data[f + 1] * c
            else:
                return data[f]
        
        # Count errors
        errors = {}
        for result in self.results:
            if not result.success and result.error_message:
                error_type = result.error_message.split(':')[0] if ':' in result.error_message else result.error_message
                errors[error_type] = errors.get(error_type, 0) + 1
        
        return LoadTestResults(
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            total_time=total_time,
            requests_per_second=total_requests / total_time if total_time > 0 else 0,
            avg_response_time=statistics.mean(response_times) if response_times else 0,
            min_response_time=min(response_times) if response_times else 0,
            max_response_time=max(response_times) if response_times else 0,
            p50_response_time=percentile(response_times, 50),
            p95_response_time=percentile(response_times, 95),
            p99_response_time=percentile(response_times, 99),
            error_rate=(failed_requests / total_requests * 100) if total_requests > 0 else 0,
            errors=errors
        )
    
    def print_results(self, results: LoadTestResults):
        """Print formatted test results"""
        print("\n" + "=" * 60)
        print("LOAD TEST RESULTS")
        print("=" * 60)
        
        print(f"Test Duration: {results.total_time:.2f} seconds")
        print(f"Total Requests: {results.total_requests}")
        print(f"Successful Requests: {results.successful_requests}")
        print(f"Failed Requests: {results.failed_requests}")
        print(f"Error Rate: {results.error_rate:.2f}%")
        print(f"Requests/Second: {results.requests_per_second:.2f}")
        
        print("\nResponse Time Statistics:")
        print(f"  Average: {results.avg_response_time*1000:.2f} ms")
        print(f"  Minimum: {results.min_response_time*1000:.2f} ms")
        print(f"  Maximum: {results.max_response_time*1000:.2f} ms")
        print(f"  50th Percentile: {results.p50_response_time*1000:.2f} ms")
        print(f"  95th Percentile: {results.p95_response_time*1000:.2f} ms")
        print(f"  99th Percentile: {results.p99_response_time*1000:.2f} ms")
        
        if results.errors:
            print("\nError Breakdown:")
            for error_type, count in results.errors.items():
                print(f"  {error_type}: {count}")
        
        print("=" * 60)
    
    def save_results_json(self, results: LoadTestResults, filename: str):
        """Save results to JSON file"""
        results_dict = asdict(results)
        results_dict['test_config'] = {
            'target_url': self.target_url,
            'concurrent_users': self.concurrent_users,
            'total_requests': self.total_requests,
            'duration': self.duration,
            'request_delay': self.request_delay,
            'timeout': self.timeout,
            'manifest_path': self.manifest_path,
            'simulate_dash': self.simulate_dash,
            'segment_interval': self.segment_interval,
            'disable_cache': self.disable_cache,
            'max_earth_directories': self.max_earth_directories
        }
        results_dict['timestamp'] = datetime.now().isoformat()
        
        with open(filename, 'w') as f:
            json.dump(results_dict, f, indent=2)
        
        print(f"\nResults saved to: {filename}")


def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(
        description="Load Generator for TCP/HTTP Load Balancer",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        '--url', '-u',
        default='http://host.docker.internal:8080',
        help='Target URL to load test'
    )
    
    parser.add_argument(
        '--concurrent', '-c',
        type=int,
        default=10,
        help='Number of concurrent users/connections'
    )
    
    parser.add_argument(
        '--requests', '-n',
        type=int,
        default=100,
        help='Total number of requests to make'
    )
    
    parser.add_argument(
        '--duration', '-d',
        type=int,
        help='Test duration in seconds (overrides --requests if specified)'
    )
    
    parser.add_argument(
        '--delay',
        type=float,
        default=0.0,
        help='Delay between requests per user in seconds'
    )
    
    parser.add_argument(
        '--timeout', '-t',
        type=float,
        default=30.0,
        help='Request timeout in seconds'
    )
    
    parser.add_argument(
        '--output', '-o',
        help='Output file for JSON results'
    )
    
    parser.add_argument(
        '--endpoint',
        default='/',
        help='Endpoint path to append to URL'
    )
    
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level for detailed error information'
    )
    
    parser.add_argument(
        '--manifest-path',
        default='/Static/Earth/manifest.mpd',
        help='Path to DASH manifest file (for DASH simulation) - Note: In DASH mode, random Earth directories are automatically selected'
    )
    
    parser.add_argument(
        '--disable-dash',
        action='store_true',
        help='Disable DASH simulation and use standard HTTP requests'
    )
    
    parser.add_argument(
        '--segment-interval',
        type=float,
        default=2.0,
        help='Interval between DASH segment requests in seconds (default: 2.0)'
    )
    
    parser.add_argument(
        '--enable-cache',
        action='store_true',
        help='Enable HTTP caching (by default, caching is disabled for realistic load testing)'
    )
    
    parser.add_argument(
        '--max-earth-dirs',
        type=int,
        default=100,
        help='Maximum number of Earth directories to randomly select from (Earth1 to EarthN)'
    )
    
    args = parser.parse_args()
    
    # Construct full URL - for DASH mode, use base URL without endpoint
    if args.disable_dash:
        target_url = args.url.rstrip('/') + args.endpoint
        simulate_dash = False
    else:
        target_url = args.url.rstrip('/')
        simulate_dash = True
    
    # If duration is specified, set requests to a very high number
    total_requests = args.requests
    if args.duration:
        total_requests = 999999  # Effectively unlimited
    
    # Create and run load generator
    load_generator = LoadGenerator(
        target_url=target_url,
        concurrent_users=args.concurrent,
        total_requests=total_requests,
        duration=args.duration,
        request_delay=args.delay,
        timeout=args.timeout,
        log_level=args.log_level,
        manifest_path=args.manifest_path,
        simulate_dash=simulate_dash,
        segment_interval=args.segment_interval,
        disable_cache=not args.enable_cache,  # Invert since we default to disable cache
        max_earth_directories=args.max_earth_dirs
    )
    
    try:
        results = load_generator.run_load_test()
        load_generator.print_results(results)
        
        # Save results to file if requested
        if args.output:
            load_generator.save_results_json(results, args.output)
    
    except KeyboardInterrupt:
        print("\nLoad test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError running load test: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
