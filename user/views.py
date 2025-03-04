from rest_framework.views import APIView
from rest_framework import status, permissions
from rest_framework.response import Response
from user.serializers import (
    UserSerializer,
    UserSignOutSerializer,
    UserEditSerializer,
    GoogleUserSerializer,
)
from user.permissions import IsAuthenticatedOrReadOrSignUp
from rest_framework.generics import get_object_or_404
from user.models import User
from django.shortcuts import redirect
import os
import requests
from rest_framework_simplejwt.tokens import RefreshToken

FRONT_BASEURI = "http://127.0.0.1:5500/"
GOOGLE_CALLBACK_URI = FRONT_BASEURI + "index.html"


class UserSignView(APIView):
    """유저 가입 뷰

    회원가입, 탈퇴, 유저정보 조회, 유저정보 수정을 처리하는 View입니다.
    """

    permission_classes = (IsAuthenticatedOrReadOrSignUp,)

    def post(self, request):
        """회원가입

        post요청과 username, email, password, password2를 입력받습니다.
        입력 값을 검사하여, 정상 시 유저를 생성합니다.

        Returns:
            상태코드 201: 회원가입성공. "회원가입성공" 메세지 반환.
            상태코드 400: 입력값 에러. (serialized.error메세지)
        """
        serialized = UserSerializer(data=request.data)
        if serialized.is_valid():
            serialized.save()
            return Response({"message": "회원가입성공"}, status=status.HTTP_201_CREATED)
        return Response(serialized.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request):
        """회원탈퇴

        put요청과 password를 입력받습니다.
        현재 로그인 중인 유저(request.user)를 찾고 password를 검사합니다.
        정상 시 해당 유저의 is_active 값을 False로 바꾸어 저장합니다.

        Returns:
            상태코드 200: 탈퇴성공. "회원탈퇴성공" 메세지 반환.
            상태코드 400: 비밀번호 틀림.
            상태코드 401: 만료토큰/로그인안함.
            상태코드 404: 유저가 없음.
        """
        user = get_object_or_404(User, id=request.user.id)
        serializer = UserSignOutSerializer(user, request.data)
        if serializer.is_valid():
            user.is_active = False
            user.save()
            return Response({"message": "회원탈퇴성공"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request, user_id=None):
        """회원조회

        get요청과, 선택적으로 user_id를 입력받습니다.
        user_id 입력이 있다면 대상의 정보를,
        없다면 request.user의 정보를 찾아 반환합니다.

        Args:
            user_id (int): 선택적 입력. url 매개 변수.

        Returns:
            상태코드 200: 조회한 회원정보 반환.
            상태코드 404: 유저가 없음.
        """
        user_id_ = user_id if user_id else request.user.id
        user = get_object_or_404(User, id=user_id_)
        serialized = UserSerializer(user)
        return Response(serialized.data, status=status.HTTP_200_OK)

    def patch(self, request):
        """회원수정

        patch요청과 current_password, 수정할 데이터를 입력받습니다.
        패스워드를 수정할 경우 password2도 입력받습니다.
        현재 로그인 중인 유저(request.user)를 찾고 current_password를 검사합니다.
        수정할 값들을 검사하여 정상 시 유저정보를 수정합니다.

        Returns:
            상태코드 200: 수정성공. "회원수정성공" 메세지 반환.
            상태코드 400: 비밀번호 틀림. 수정할 값 틀림.
            상태코드 404: 유저가 없음.
        """
        user = get_object_or_404(User, id=request.user.id)
        serialized = UserEditSerializer(user, request.data, partial=True)
        if serialized.is_valid():
            serialized.save()
            return Response({"message": "회원수정성공"}, status=status.HTTP_200_OK)
        return Response(serialized.errors, status=status.HTTP_400_BAD_REQUEST)


class GoogleURLView(APIView):
    """GoogleURLView 리다이렉션을 위한 뷰

    frontend에게 구글 계정을 이용한 로그인을 위해 callback uri과 client_id를 제공합니다.
    """

    def get(self, request):
        """GoogleURLView.get

        frontend에게 구글 계정을 이용한 로그인을 위해 callback uri과 client_id를 제공합니다.

        Return:
            정상 시: 200 / client_id와 redirect_uri

        client_id는 로그인시 사용되는 구글 api 클라이언트의 고유 id이고, redirect_uri는 해당 클라이언트에서
        어떤 url로 access_token을 보낼지 결정합니다.

        """
        client_id = os.environ.get("SOCIAL_AUTH_GOOGLE_CLIENT_ID")
        return Response(
            {"client_id": client_id, "redirect_uri": GOOGLE_CALLBACK_URI},
            status=status.HTTP_200_OK,
        )


class GoogleTokenView(APIView):
    """GoogleTokenView 토큰 발행을 위한 뷰

    frontend로부터 accesstoken을 제공받아 구글에서 유저정보를 조회하고 그에 따라 토큰을 생성합니다.
    """

    def post(self, request):
        """GoogleTokenView.post

        request body에서 accesstoken을 제공받습니다.
        이를 통해 구글에서 유저정보를 불러옵니다.
        불러온 유저정보가 이미 DB에 있는지 확인하고 유무 여부에 따라 회원가입을 한 뒤
        회원정보를 토대로 refresh token과 access token을 만들어 반환합니다.
        """
        access_token = request.data.get("access_token")

        if access_token is None:
            return Response(
                {"message": "토큰이 없습니다."}, status=status.HTTP_401_UNAUTHORIZED
            )
        headers = {"Authorization": f"Bearer {access_token}"}
        user_info_request = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo", headers=headers
        )
        user_data = user_info_request.json()
        email = user_data.get("email")
        if email is None:
            return Response(
                {"message": "유저정보에 접근할 수 없습니다."}, status=status.HTTP_401_UNAUTHORIZED
            )
        username = email.split("@")[0] + "_g"
        password = "0000"
        print(user_data)
        try:
            user = User.objects.get(email=email)
        except:
            serializer = GoogleUserSerializer(
                data={"email": email, "username": username, "password": password}
            )
            if serializer.is_valid():
                serializer.save()
            else:
                return Response(serializer.errors)

            user = get_object_or_404(User, email=email)
        if user.logintype != "GOOGLE":
            return Response(
                {"message": "소셜 로그인 이메일이 아닙니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        refresh = RefreshToken.for_user(user)
        refresh["email"] = user.email
        refresh["username"] = user.username
        refresh["logintype"] = user.logintype
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            status=status.HTTP_200_OK,
        )
