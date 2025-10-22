#!/usr/bin/env python3
"""
DASH Load Generator (Blast-only)

This script blasts a target load balancer with MPEG-DASH traffic using
concurrent clients. It is designed to sustain very high loads without
storing per-request results in memory.
"""

import asyncio
import aiohttp
import argparse
import time
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional
import threading
import signal
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
import random


@dataclass
class DashSegment:
    """Information about a DASH segment"""
    url: str
    segment_type: str  # 'init' or 'media'
    representation_id: str
    segment_number: Optional[int] = None

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


# Constants
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_ENDPOINT = "/"
DEFAULT_MANIFEST_PATH = "/video-1/manifest.mpd"
MAX_VIDEO_DIRECTORIES = 12

# Fixed-memory histogram for response times (ms)
# Covers 0..HISTOGRAM_MAX_MS with HISTOGRAM_BUCKET_MS resolution
HISTOGRAM_BUCKET_MS = 5
HISTOGRAM_MAX_MS = 20000

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
            root = ET.fromstring(manifest_content)
            
            ns = {'dash': 'urn:mpeg:dash:schema:mpd:2011'}
            
            adaptation_sets = root.findall('.//dash:AdaptationSet', ns)
            
            for adaptation_set in adaptation_sets:
                representations = adaptation_set.findall('dash:Representation', ns)
                
                for representation in representations:
                    rep_id = representation.get('id', 'unknown')
                    
                    segment_template = representation.find('dash:SegmentTemplate', ns)
                    if segment_template is not None:
                        init_template = segment_template.get('initialization')
                        media_template = segment_template.get('media')
                        start_number = int(segment_template.get('startNumber', '1'))
                        
                        base_segment_url = urljoin(manifest_url, './')
                        
                        if init_template:
                            init_url = init_template.replace('$RepresentationID$', rep_id)
                            segments.append(DashSegment(
                                url=urljoin(base_segment_url, init_url),
                                segment_type='init',
                                representation_id=rep_id
                            ))
                        
                        segment_timeline = segment_template.find('dash:SegmentTimeline', ns)
                        if segment_timeline is not None:
                            s_elements = segment_timeline.findall('dash:S', ns)
                            segment_number = start_number
                            
                            for s_element in s_elements:
                                repeat = int(s_element.get('r', '0'))
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
    """Main load generator class (blast-only DASH)."""
    
    def __init__(self, target_url: str, concurrent_users: int = 10,
                 duration: Optional[int] = None, log_level: str = "INFO",
                 no_keepalive: bool = False):
        self.target_url = target_url
        self.concurrent_users = concurrent_users
        self.duration = duration
        self.no_keepalive = no_keepalive
        
        # Timing
        self.timeout = DEFAULT_TIMEOUT_SECONDS
        self.start_time = 0.0
        self.end_time = 0.0
        self.stop_event = threading.Event()
        
        # DASH
        self.max_video_directories = MAX_VIDEO_DIRECTORIES
        self.manifest_path = DEFAULT_MANIFEST_PATH
        self.manifest_parser = DashManifestParser(target_url)
        
        # Aggregated counters (thread-safe)
        self.metrics_lock = threading.Lock()
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.response_time_sum = 0.0
        self.response_time_min = float('inf')
        self.response_time_max = 0.0
        self.errors: Dict[str, int] = {}
        
        # Fixed-memory histogram
        self.bucket_ms = HISTOGRAM_BUCKET_MS
        self.max_ms = HISTOGRAM_MAX_MS
        self.num_buckets = int(self.max_ms // self.bucket_ms) + 1  # includes overflow edge
        self.histogram: List[int] = [0] * self.num_buckets
        self.overflow_count = 0
        
        self._setup_logging(log_level)
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _setup_logging(self, log_level: str):
        """Setup logging configuration"""
        self.logger = logging.getLogger('LoadGenerator')
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def _record_result(self, success: bool, response_time: float, error_message: Optional[str] = None):
        """Record a single request outcome into aggregated metrics."""
        duration_ms = int(response_time * 1000)
        bucket_index = min(duration_ms // self.bucket_ms, self.num_buckets - 1)
        with self.metrics_lock:
            self.total_requests += 1
            if success:
                self.successful_requests += 1
            else:
                self.failed_requests += 1
                if error_message:
                    key = error_message.split(':')[0] if ':' in error_message else error_message
                    self.errors[key] = self.errors.get(key, 0) + 1
            self.response_time_sum += response_time
            if response_time < self.response_time_min:
                self.response_time_min = response_time
            if response_time > self.response_time_max:
                self.response_time_max = response_time
            self.histogram[bucket_index] += 1
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}. Shutting down gracefully...")
        print(f"\nReceived signal {signum}. Shutting down gracefully...")
        self.stop_event.set()
    
    async def _make_request(self, session: aiohttp.ClientSession, request_id: int, 
                           url: Optional[str] = None, segment_type: Optional[str] = None) -> None:
        """Make a single HTTP GET request and update aggregated metrics."""
        start_time = time.time()
        timestamp = start_time
        base_url = url if url else self.target_url
        request_url = base_url
        headers = {
            'User-Agent': f'LoadGenerator-{request_id}'
        }
        
        try:
            async with session.get(
                request_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as response:
                await response.read()
                end_time = time.time()
                
                self.logger.debug(f"Request {request_id}: SUCCESS - Status: {response.status}, "
                                f"Time: {(end_time - start_time)*1000:.2f}ms - URL: {request_url} "
                                f"Type: {segment_type or 'standard'}")
                self._record_result(True, end_time - start_time)
                
        except asyncio.TimeoutError:
            end_time = time.time()
            error_msg = "Timeout"
            self.logger.warning(f"Request {request_id}: {error_msg} - URL: {request_url}")
            self._record_result(False, end_time - start_time, error_msg)
        except aiohttp.ClientConnectorError as e:
            end_time = time.time()
            os_err = getattr(e, 'os_error', None)
            errno_val = getattr(os_err, 'errno', None)
            error_msg = f"Connection error: {type(e).__name__}: {str(e)}"
            if errno_val is not None:
                error_msg += f" (errno={errno_val})"
            self.logger.error(f"Request {request_id}: {error_msg} - URL: {request_url}")
            self._record_result(False, end_time - start_time, error_msg)
        except aiohttp.ClientResponseError as e:
            end_time = time.time()
            error_msg = f"HTTP {e.status} error: {str(e)}"
            self.logger.error(f"Request {request_id}: {error_msg} - URL: {request_url}")
            self._record_result(False, end_time - start_time, f"HTTP Error {e.status}")
        except aiohttp.ClientError as e:
            end_time = time.time()
            error_msg = f"Client error: {type(e).__name__}: {str(e)}"
            self.logger.error(f"Request {request_id}: {error_msg} - URL: {request_url}")
            self._record_result(False, end_time - start_time, f"Client Error: {type(e).__name__}")
        except Exception as e:
            end_time = time.time()
            error_msg = f"Unexpected error: {type(e).__name__}: {str(e)}"
            self.logger.error(f"Request {request_id}: {error_msg} - URL: {request_url}")
            self._record_result(False, end_time - start_time, f"Unexpected Error: {type(e).__name__}")
    
    async def _worker(self, worker_id: int, session: aiohttp.ClientSession):
        """DASH worker that continuously fetches segments with no throttling."""
        worker_start_time = time.time()
        self.logger.debug(f"Worker {worker_id}: Started")
        await self._dash_worker(worker_id, session)
        worker_end_time = time.time()
        self.logger.debug(f"Worker {worker_id}: Stopped after {worker_end_time - worker_start_time:.2f}s")
    
    async def _dash_worker(self, worker_id: int, session: aiohttp.ClientSession):
        """DASH simulation worker that continuously fetches segments in a loop"""
        video_number = random.randint(1, self.max_video_directories)
        selected_video_dir = f"video-{video_number}"
        
        manifest_path = f"/{selected_video_dir}/manifest.mpd"
        manifest_url = urljoin(self.target_url, manifest_path)
        
        self.logger.debug(f"Worker {worker_id}: Starting DASH client simulation for {selected_video_dir}")
        self.logger.info(f"Worker {worker_id}: Selected video directory '{selected_video_dir}'")
        
        await self._make_request(session, f"{worker_id}-manifest", manifest_url, "manifest")
        
        try:
            segments = await self.manifest_parser.fetch_and_parse_manifest(session, manifest_url)
        except Exception as e:
            self.logger.error(f"Worker {worker_id}: Failed to parse manifest for {selected_video_dir}: {e}")
            return
        
        if not segments:
            self.logger.error(f"Worker {worker_id}: No segments found in manifest")
            return
        
        init_segments = [s for s in segments if s.segment_type == 'init']
        media_segments = [s for s in segments if s.segment_type == 'media']
        
        for i, segment in enumerate(init_segments):
            if self.stop_event.is_set():
                return
            await self._make_request(session, f"{worker_id}-init-{i}", 
                                     segment.url, f"init-{segment.representation_id}")
        
        segment_index = 0
        request_count = 0
        
        while not self.stop_event.is_set():
            if self.duration and (time.time() - self.start_time) >= self.duration:
                break
            
            if media_segments:
                current_segment = media_segments[segment_index % len(media_segments)]
                segment_index += 1
                
                await self._make_request(
                    session, 
                    f"{worker_id}-media-{segment_index}", 
                    current_segment.url, 
                    f"media-{current_segment.representation_id}-{current_segment.segment_number}"
                )
            else:
                self.logger.warning(f"Worker {worker_id}: No media segments available")
                break
        
        self.logger.debug(f"Worker {worker_id}: Completed segment requests")
    
    # Non-blast simulation helper removed in blast-only refactor
    
    async def _run_async_load_test(self):
        """Run the asynchronous load test (blast-only)."""
        # Unlimited connector limits
        computed_limit = 0
        computed_per_host = 0
        connector = aiohttp.TCPConnector(
            limit=computed_limit,
            limit_per_host=computed_per_host,
            keepalive_timeout=30,
            enable_cleanup_closed=True,
            force_close=self.no_keepalive
        )
        
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        default_headers = {'User-Agent': 'LoadGenerator/1.0'}
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=default_headers
        ) as session:
            tasks = []
            for i in range(self.concurrent_users):
                task = asyncio.create_task(self._worker(i, session))
                tasks.append(task)
            
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def run_load_test(self) -> LoadTestResults:
        """Run the load test and return results"""
        self.logger.info(f"Starting load test with {self.concurrent_users} concurrent users")
        self.logger.info(f"Target URL: {self.target_url}")
        if self.duration:
            self.logger.info(f"Duration: {self.duration} seconds")
        self.logger.info(f"Request timeout: {self.timeout} seconds")
        
        print(f"Starting load test...")
        print(f"Target URL: {self.target_url}")
        print(f"Concurrent users: {self.concurrent_users}")
        if self.duration:
            print(f"Duration: {self.duration} seconds")
        print(f"Request timeout: {self.timeout} seconds")
        print(f"Log level: {self.logger.level}")
        print("-" * 50)
        
        self.start_time = time.time()
        
        try:
            asyncio.run(self._run_async_load_test())
        except KeyboardInterrupt:
            print("\nLoad test interrupted by user")
        
        self.end_time = time.time()
        
        return self._calculate_results()

    # Diagnostics removed in blast-only refactor
    
    def _calculate_results(self) -> LoadTestResults:
        """Calculate and return test results"""
        total_requests = self.total_requests
        if total_requests == 0:
            return LoadTestResults(
                total_requests=0, successful_requests=0, failed_requests=0,
                total_time=0, requests_per_second=0, avg_response_time=0,
                min_response_time=0, max_response_time=0,
                p50_response_time=0, p95_response_time=0, p99_response_time=0,
                error_rate=0, errors={}
            )
        
        successful_requests = self.successful_requests
        failed_requests = self.failed_requests
        total_time = self.end_time - self.start_time
        
        # Compute percentiles from histogram
        def percentile_from_histogram(pct: float) -> float:
            if total_requests == 0:
                return 0.0
            target = max(1, int((pct / 100.0) * total_requests))
            cumulative = 0
            for idx, count in enumerate(self.histogram):
                cumulative += count
                if cumulative >= target:
                    # Return bucket mid-point in seconds
                    bucket_start_ms = idx * self.bucket_ms
                    bucket_mid_ms = bucket_start_ms + (self.bucket_ms / 2.0)
                    return bucket_mid_ms / 1000.0
            # Fallback to max
            return self.response_time_max

        return LoadTestResults(
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            total_time=total_time,
            requests_per_second=total_requests / total_time if total_time > 0 else 0,
            avg_response_time=(self.response_time_sum / total_requests) if total_requests > 0 else 0.0,
            min_response_time=(0.0 if self.response_time_min == float('inf') else self.response_time_min),
            max_response_time=self.response_time_max,
            p50_response_time=percentile_from_histogram(50.0),
            p95_response_time=percentile_from_histogram(95.0),
            p99_response_time=percentile_from_histogram(99.0),
            error_rate=(failed_requests / total_requests * 100.0) if total_requests > 0 else 0.0,
            errors=self.errors.copy()
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
        """Intentionally removed: JSON output not supported in blast-only refactor."""
        raise NotImplementedError("JSON output has been removed in the blast-only refactor.")


def main():
    """Main function with command line argument parsing"""
    parser = argparse.ArgumentParser(
        description="Blast-only MPEG-DASH Load Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        '--url', '-u',
        default='http://load-balancer:8080',
        help='Target base URL (e.g., http://host.docker.internal:8080)'
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
        help='Test duration in seconds (blast runs until duration or Ctrl+C)'
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
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level for detailed error information'
    )
    
    parser.add_argument(
        '--no-keepalive',
        action='store_true',
        help='Disable HTTP keep-alive so each request opens a new TCP connection'
    )
    
    
    
    args = parser.parse_args()
    
    # Always simulate DASH; ensure trailing slash per DEFAULT_ENDPOINT
    target_url = args.url.rstrip('/') + DEFAULT_ENDPOINT
    effective_concurrency = args.concurrent

    load_generator = LoadGenerator(
        target_url=target_url,
        concurrent_users=effective_concurrency,
        duration=args.duration,
        log_level=args.log_level,
        no_keepalive=args.no_keepalive
    )
    
    try:
        results = load_generator.run_load_test()
        load_generator.print_results(results)
    
    except KeyboardInterrupt:
        print("\nLoad test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nError running load test: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
