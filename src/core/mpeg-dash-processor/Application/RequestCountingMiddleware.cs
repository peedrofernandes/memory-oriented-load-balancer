using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;

public sealed class RequestCountingMiddleware
{
	private readonly RequestDelegate _next;
	private readonly RequestCounter _requestCounter;

	public RequestCountingMiddleware(RequestDelegate next, RequestCounter requestCounter)
	{
		_next = next;
		_requestCounter = requestCounter;
	}

	public async Task InvokeAsync(HttpContext context)
	{
		_requestCounter.Increment();
		try
		{
			await _next(context);
		}
		finally
		{
			_requestCounter.Decrement();
		}
	}
}


