using System.Threading;

public sealed class RequestCounter
{
	private int _activeRequestCount;

	public int Get()
	{
		return Volatile.Read(ref _activeRequestCount);
	}

	public void Increment()
	{
		Interlocked.Increment(ref _activeRequestCount);
	}

	public void Decrement()
	{
		// Ensure it doesn't go below zero
		int newValue = Interlocked.Decrement(ref _activeRequestCount);
		if (newValue < 0)
		{
			// Correct counter if it went negative due to mismatched calls
			Interlocked.Exchange(ref _activeRequestCount, 0);
		}
	}
}


