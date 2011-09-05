class Observable(object):
    """
    Implementation of the observer design pattern.
    """

    def __init__(self):
        self._subscribers = set()

    def subscribe(self, func):
        if not callable(func):
            raise TypeError("Parameter of must be callable.")
        self._subscribers.add(func)

    def unsubscribe(self, func):
        self._subscribers.remove(func)

    def __call__(self, *args, **kwargs):
        for func in self._subscribers:
            func(*args, **kwargs)

