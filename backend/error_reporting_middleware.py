from __future__ import print_function
import traceback
import sys

class ProcessExceptionMiddleware(object):
    def __init__(self, get_response):
        # One-time configuration and initialization.
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        return response
        
    def process_exception(self, request, exception):
        # Just print the exception object to stdout
        print(exception)

        # Print the familiar Python-style traceback to stderr
        traceback.print_exc()

        # Write the traceback to a file or similar
        myfile.write(''.join(traceback.format_exception(*sys.exc_info())))