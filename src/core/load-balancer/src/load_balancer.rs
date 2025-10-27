use crate::strategies::strategy::ServerSelectionStrategy;
use std::collections::{HashMap, HashSet};
use std::net::SocketAddr;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use hyper::{Body, Client, Request, Response, Uri};
use hyper::service::{make_service_fn, service_fn};
use http::{HeaderMap, HeaderValue};
use std::time::Duration;
use tokio::time::timeout;

pub struct LoadBalancer {
    servers: Vec<String>,
    strategy: Arc<dyn ServerSelectionStrategy>,
    request_counter: Arc<AtomicU64>,
}

impl LoadBalancer {
    pub fn new(servers: Vec<String>, strategy: Arc<dyn ServerSelectionStrategy>) -> Self {
        let mut counts = HashMap::new();
        for s in &servers {
            counts.insert(s.clone(), 0u64);
        }

        Self { 
            servers, 
            strategy,
            request_counter: Arc::new(AtomicU64::new(0)),
        }
    }

    pub async fn start(&self, bind_address: &str) -> Result<(), Box<dyn std::error::Error>> {
        let addr: SocketAddr = bind_address.parse()?;
        println!("HTTP load balancer listening on {}", bind_address);
        println!("Available servers: {:?}", self.servers);

        let servers = self.servers.clone();
        let strategy = Arc::clone(&self.strategy);
        let request_counter = Arc::clone(&self.request_counter);

        // Shared HTTP client for outbound requests
        let client: Client<hyper::client::HttpConnector, Body> = Client::new();
        let client = Arc::new(client);

        let make_svc = make_service_fn(move |_conn| {
            let servers = servers.clone();
            let strategy = Arc::clone(&strategy);
            let request_counter = Arc::clone(&request_counter);
            let client = Arc::clone(&client);

            async move {
                Ok::<_, hyper::Error>(service_fn(move |req: Request<Body>| {
                    let servers = servers.clone();
                    let strategy = Arc::clone(&strategy);
                    let request_counter = Arc::clone(&request_counter);
                    let client = Arc::clone(&client);

                    async move {
                        // Increment per-request counter
                        let _ = request_counter.fetch_add(1, Ordering::Relaxed);

                        // Extract immutable request data for retries
                        let method = req.method().clone();
                        let version = req.version();
                        let path_and_query = req
                            .uri()
                            .path_and_query()
                            .map(|pq| pq.as_str().to_string())
                            .unwrap_or_else(|| "/".to_string());
                        let original_headers = req.headers().clone();
                        let body_bytes = match hyper::body::to_bytes(req.into_body()).await {
                            Ok(b) => b,
                            Err(_) => {
                                return Ok::<_, hyper::Error>(response_with_status(
                                    http::StatusCode::BAD_REQUEST,
                                    "Failed to read request body",
                                ));
                            }
                        };

                        // Retry across available servers with a 5s timeout per attempt
                        let mut attempted: HashSet<String> = HashSet::new();

                        loop {
                            // Build candidate list excluding attempted servers
                            let candidates: Vec<String> = servers
                                .iter()
                                .filter(|s| !attempted.contains(*s))
                                .cloned()
                                .collect();

                            if candidates.is_empty() {
                                return Ok::<_, hyper::Error>(response_with_status(
                                    http::StatusCode::BAD_GATEWAY,
                                    "No available servers",
                                ));
                            }

                            let backend = match strategy.pick_server(&candidates) {
                                Some(s) => s,
                                None => {
                                    return Ok::<_, hyper::Error>(response_with_status(
                                        http::StatusCode::BAD_GATEWAY,
                                        "No available servers",
                                    ));
                                }
                            };
                            attempted.insert(backend.clone());

                            // Build new URI with backend authority
                            let new_uri: Uri = match Uri::builder()
                                .scheme("http")
                                .authority(backend.as_str())
                                .path_and_query(path_and_query.as_str())
                                .build() {
                                    Ok(u) => u,
                                    Err(_) => {
                                        // Bad URI for this backend, try another
                                        continue;
                                    }
                                };

                            // Build outbound request
                            let mut outbound_req = match Request::builder()
                                .method(method.clone())
                                .version(version)
                                .uri(new_uri)
                                .body(Body::from(body_bytes.clone())) {
                                    Ok(r) => r,
                                    Err(_) => {
                                        // Failed to build request, try another backend
                                        continue;
                                    }
                                };

                            // Copy headers, sanitize hop-by-hop, and set Host
                            {
                                let h = outbound_req.headers_mut();
                                // Extend with original headers
                                for (k, v) in original_headers.iter() {
                                    // Skip hop-by-hop here; sanitize after extend as well
                                    h.append(k, v.clone());
                                }
                                sanitize_hop_by_hop_headers(h);
                                h.insert(
                                    http::header::HOST,
                                    HeaderValue::from_str(backend.as_str()).unwrap_or(HeaderValue::from_static("")),
                                );
                            }

                            // Send with timeout
                            match timeout(Duration::from_secs(5), client.request(outbound_req)).await {
                                Ok(Ok(mut resp)) => {
                                    sanitize_hop_by_hop_headers(resp.headers_mut());
                                    return Ok::<_, hyper::Error>(resp);
                                }
                                Ok(Err(_e)) => {
                                    // Upstream error, try next server
                                    continue;
                                }
                                Err(_elapsed) => {
                                    // Timed out, try next server
                                    continue;
                                }
                            }
                        }
                    }
                }))
            }
        });

        hyper::Server::bind(&addr).serve(make_svc).await?;
        Ok(())
    }
}

fn sanitize_hop_by_hop_headers(headers: &mut HeaderMap) {
    // Remove hop-by-hop headers per RFC 7230
    static HOP_HEADERS: &[&str] = &[
        "connection",
        "proxy-connection",
        "keep-alive",
        "transfer-encoding",
        "upgrade",
        "te",
        "trailer",
    ];
    for name in HOP_HEADERS {
        headers.remove(*name);
    }
}

fn response_with_status(status: http::StatusCode, msg: &str) -> Response<Body> {
    Response::builder()
        .status(status)
        .header(http::header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .body(Body::from(msg.to_string()))
        .unwrap_or_else(|_| Response::new(Body::from(msg.to_string())))
}
