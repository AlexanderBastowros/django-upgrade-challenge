from rest_framework.pagination import LimitOffsetPagination, PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class LargeResultsSetPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 500
